
#       .|/
# (\/)(o,,,o)(\/)


# # specification example
# 
# name : Mu
# type : Unique
# 
# name   : SmallString
# c-type : struct { uint8_t size ; char data[ 7 ] ;};
# 
# name   : Cons
# c-type : struct { struct II car ; struct II cdr ;};
# walk   : { yield( &this->car ) ; yield( &this->cdr ) ;};
# 

# __create( size )          -> mmap and initialize a new gc region of the specified size
# __alloc( register, size ) -> allocate a gc object with the given amount of storage in the given register
# __cast( ii, type )        -> mark the new object as being of the given type, presumably after readying it
# __set( register, ii )     -> set a register to ii ( if you put in an invalid ii, you've ruined everything )
# __get( register )         -> get from a register
# __data( ii )              -> it's your job to know what the data means

# any and all pointers and ii's are invalidated whenever you call __collect
# calling __alloc can call __collect, so you have to make an unlikely check
# for whether the gc ran after every allocation, and if so, refresh you data
# there is a special type you can plug in a register and check and reset it
# to see if the gc has reset since last time you touched it. alternately, you
# can pass that information around manually. or do both. I don't really care.

TEMPLATE = r"""

#ifndef ZGC_H
#define ZGC_H

//       .|/
// (\/)(o,,,o)(\/)

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <sys/mman.h>
#include <errno.h>
#include <string.h>
#include <inttypes.h>

#define zMINSLOTS         1024
#define zNUM_REGISTERS    $NUMREGISTERS
#define zNUM_UNIQUE_TYPES $UNIQUETYPES
#define zNUM_OBJECT_TYPES $OBJECTTYPES
#define zSLOT_SIZE        $SLOTSIZE

// define object type here and then determine the available immediate size based on it
// ( max of uint32, then question the user's sanity ? )
// ( or allow them to also specify a desired indirection size, which will allow manual control for wastage )

#define zSTRING( xx ) #xx
#define zSTRINGVALUE( xx ) zSTRING( xx )

#define zUNLIKELY(x) __builtin_expect((x),0)
#define zLIKELY(x) __builtin_expect((x),1)

#define zUNUSED(x) ((void)(x))

#define zGc__panic( pattern, ... ) do {                                                      \
    fprintf( stderr, "PANIC @ %s:%d :: " pattern "\n", __FILE__, __LINE__, ## __VA_ARGS__ ); \
    abort();                                                                                 \
    exit( 1 );                                                                               \
  } while(0);

struct zOT { uint16_t objectType ; };
struct zII { uint32_t indirectionIndex ; };
struct zSI { uint32_t slotIndex ; };

struct zLM { uint64_t index ; };
struct zRW { uint32_t index ; };

static const struct zII zRESERVED_NULL = (struct zII){ .indirectionIndex = 0 } ;
$UNIQUERESERVATIONS

#define zTYPE_NULL ((struct zOT){ .objectType = 0 })
$TYPEENUMERATIONS

struct zIndirection {
  struct zOT objectType ;
  char       immediate  ;
  char       _reserved  ;
  union {
    struct zSI as_slotIndex ;
    // hopefully, there will be no spacing ( because char ) and this will
    // just fill out the rest of the indirection
    char       as_immediateData [ zSLOT_SIZE - sizeof( struct zOT ) - 2 * sizeof( char ) ] ;
  };
};

union zSlot {
  char                as_chardata    [zSLOT_SIZE] ;
  struct zIndirection as_indirection              ;
};

static inline
void
z__static_assertions(
){
  _Static_assert(
    sizeof( union zSlot ) == zSLOT_SIZE,
    "slot union unexpectedly not " zSTRINGVALUE( zSLOT_SIZE ) " bytes in size"
  );
  
  _Static_assert(
    zNUM_REGISTERS != 0,
    "cannot create a gc with 0 registers"
  );
}

struct zGc {
  uint64_t    numSlots                     ; // how many total slots are available to the gc?
  struct zII  nextII                       ; // what is the index of the next indirection available to the gc?
  struct zSI  nextSI                       ; // what is the index of the next slot available to the gc?
  struct zII  registers [ zNUM_REGISTERS ] ; // root set
  union zSlot slots     []                 ; // gc'd data
};

 static inline
struct zIndirection *
zGc__indirection(
  struct zGc * gc ,
  struct zII   ii
){
  uint64_t index = gc->numSlots - 1 - ii.indirectionIndex ;
  return & gc->slots[ index ].as_indirection ;
}

static inline
union zSlot *
zGc__slot(
  struct zGc * gc ,
  struct zSI   si
){
  return & gc->slots[ si.slotIndex ];
}

static inline
uint64_t
zGc__num_objects(
  struct zGc * gc
){
  return gc->nextII.indirectionIndex - 1 ;
}

static inline
uint64_t
zGc__slots_needed_for_collection_livemaps(
  struct zGc * gc         ,
  uint64_t     numObjects
){
  zUNUSED( gc );
  // we only use 1 bit per object to track liveness
  uint64_t requiredSlots = ( ( numObjects / 8 ) / zSLOT_SIZE ) + 1 ;
  return requiredSlots ;
}

static inline
uint64_t
zGc__slots_needed_for_collection_rewrites(
  struct zGc * gc         ,
  uint64_t     numObjects
){
  zUNUSED( gc );
  uint64_t requiredSpace = numObjects * sizeof( struct zRW ) ;
  
  // we could do a mod and only add 1 if not even, or we can just always add 1 and maybe waste a few bytes
  uint64_t requiredSlots = ( requiredSpace / zSLOT_SIZE ) + 1 ;
  
  return requiredSlots ;
}

static inline
uint64_t
zGc__slots_needed_for_collection(
  struct zGc * gc         ,
  uint64_t     numObjects
){
  zUNUSED( gc );
  uint64_t livemapSpace = zGc__slots_needed_for_collection_livemaps( gc, numObjects );
  uint64_t rewriteSpace = zGc__slots_needed_for_collection_rewrites( gc, numObjects );
  return livemapSpace + rewriteSpace ;
}

static inline
struct zII
zGc__get(
  struct zGc * gc         ,
  uint64_t     registerNo
){
  if( zUNLIKELY( registerNo >= zNUM_REGISTERS ) ){
    zGc__panic( "bad registerNo" );
  }
  
  return gc->registers[ registerNo ] ;
}

static inline
void
zGc__set(
  struct zGc * gc         ,
  uint64_t     registerNo ,
  struct zII   ii
){
  if( zUNLIKELY( registerNo >= zNUM_REGISTERS ) ){
    zGc__panic( "bad registerNo" );
  }
  
  gc->registers[ registerNo ] = ii ;
}

static inline
void
zGc__stats(
  struct zGc * gc
){
  fprintf( stderr, "zgc::slots  = %" PRIu64 "\n", gc->numSlots ) ;
  fprintf( stderr, "zgc::nextII = II[%" PRIu32 "]\n", gc->nextII.indirectionIndex );
  fprintf( stderr, "zgc::nextSI = SI[%" PRIu32 "]\n", gc->nextSI.slotIndex );
  fprintf( stderr, "zgc::registers (%" PRIu32 ")\n", (uint32_t)zNUM_REGISTERS );
  for( uint64_t rn = 0 ; rn < zNUM_REGISTERS ; rn++ ){
    fprintf( stderr, "  [%" PRIu64 "] :: II[%" PRIu32 "]\n", rn, zGc__get( gc, rn ).indirectionIndex );
  }
}

static inline
struct zGc *
zGc__create(
  size_t size
){
  uint64_t numSlots = (size - sizeof( struct zGc )) / zSLOT_SIZE ;
  
  if( numSlots < zMINSLOTS ){
    zGc__panic( "you cannot specify a gc of fewer than " zSTRINGVALUE( zMINSLOTS ) " SLOTS" );
  }
  
  char * start = mmap( NULL, size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0 );
  if( start == MAP_FAILED ){
    zGc__panic( "failed to alloc memory for gc : %s", strerror( errno ) );
  }
  
  struct zGc * gc = (struct zGc *) start ;
  
  gc->numSlots = numSlots ;
  gc->nextII   = (struct zII) { .indirectionIndex = zNUM_UNIQUE_TYPES + 1 }; // 0 reserved for builtin zRESERVED_NULL
  gc->nextSI   = (struct zSI) { .slotIndex = 0 } ;
  
  for( uint64_t index = 0; index < zNUM_UNIQUE_TYPES ; index ++ ){
    struct zIndirection * indirection = zGc__indirection( gc, (struct zII){ .indirectionIndex = index });
    indirection->objectType.objectType = index ;
  }
  
  for( uint64_t index = 0; index < zNUM_REGISTERS ; index ++ ){
    zGc__set( gc, index, zRESERVED_NULL );
  }
  
  return gc ;
}

static inline
char *
zGc__data(
  struct zGc * gc ,
  struct zII   ii
){
  struct zIndirection * indirection = zGc__indirection( gc, ii );
  if( indirection->immediate ){
    return & indirection->as_immediateData[0] ;
  } else {
    return & gc->slots[ indirection->as_slotIndex.slotIndex ].as_chardata[0] ;
  }
}

static inline
void
zLM__mark(
  unsigned char * lm    ,
  uint64_t        index
){
  uint64_t byteIndex = index / 8 ;
  uint64_t bitIndex  = index % 8 ;
  
  lm[ byteIndex ] |= ( 1u << bitIndex ) ;
}

static inline
unsigned char
zLM__marked(
  unsigned char * lm    ,
  uint64_t        index
){
  uint64_t byteIndex = index / 8 ;
  uint64_t bitIndex  = index % 8 ;
  
  return ( lm[ byteIndex ] & ( 1u << bitIndex ) );
}

static inline
void
zGc__collect(
  struct zGc * gc
){
  // allocate liveness bitmaps
  // allocate slot rewrite arrays
  
  // we first use the rewrite array as a stack for live item descent
  // for each root
  //   mark root item in live map, push to live item descent
  // while items in live item descent
  //   pop item
  //   for each child of item
  //     if child not live
  //       mark child live
  //       push to item descent
  
  // scan liveness bitmaps
  // determine and record new location to rewrite array
  
  // scan liveness bitmaps
  // rewrite indirections and slots
  
  // rewrite registers
  
  puts("");
  puts("pre-collect");
  zGc__stats( gc );
  
  uint64_t livemapSlots = zGc__slots_needed_for_collection_livemaps( gc, gc->nextII.indirectionIndex );
  uint64_t rewriteSlots = zGc__slots_needed_for_collection_rewrites( gc, gc->nextII.indirectionIndex );
  
  unsigned char * livemap = (unsigned char *) & gc->slots[ gc->nextSI.slotIndex ].as_chardata[0] ;
  struct zRW * rewrites = (struct zRW *) & gc->slots[ gc->nextSI.slotIndex + livemapSlots ].as_chardata[0] ;
  
  memset( livemap, 0, livemapSlots * sizeof( union zSlot ) );
  memset( rewrites, 0, rewriteSlots * sizeof( union zSlot ) );
  
  // we first use the rewrite array as a stack for live item descent
  // we'll keep track of what's alive in the livemap, which is a big fat bitmap
  
  // first preload the descent array with whatevers in the current registers
  uint64_t finalDescentIndex = 0 ;
  for( uint64_t registerIndex = 0 ; registerIndex < zNUM_REGISTERS ; registerIndex ++ ){
    if( gc->registers[ registerIndex ].indirectionIndex > zNUM_UNIQUE_TYPES ){
      rewrites[ finalDescentIndex ].index = gc->registers[ registerIndex ].indirectionIndex ;
      zLM__mark( livemap, gc->registers[ registerIndex ].indirectionIndex );
      finalDescentIndex ++ ;
    }
  }
  
  // now we'll descend the current object heirarchy and create the livemap
  uint64_t currentDescentIndex = 0 ;
  while( currentDescentIndex < finalDescentIndex ){
    struct zIndirection * indirection =
      zGc__indirection( gc, (struct zII){ .indirectionIndex = rewrites[ currentDescentIndex ].index } )
      ;
    
    // fprintf(
    //   stderr, 
    //   "descent/RW[%llu]=II[%llu]=[%p] ot=%llu\n",
    //   (unsigned long long) currentDescentIndex,
    //   (unsigned long long) rewrites[ currentDescentIndex ].index,
    //   indirection ,
    //   (unsigned long long) indirection->objectType.objectType
    // );
    
    #define yield( ptr ) \
      do{ \
        if(! zLM__marked( livemap, (ptr)->indirectionIndex ) ){ \
          if( (ptr)->indirectionIndex > zNUM_UNIQUE_TYPES ){ \
            rewrites[ finalDescentIndex++ ].index = (ptr)->indirectionIndex ; \
            zLM__mark( livemap, (ptr)->indirectionIndex ); \
          } \
        } \
      } while (0)
    
    switch( indirection->objectType.objectType ){
      $TYPEWALKS
      default:
        zGc__panic( "unknown type :: %llu", (unsigned long long) indirection->objectType.objectType );
    }
    
    #undef yield
    
    currentDescentIndex ++ ;
  }
  
  // now we need to create to create a rewrite array
  // scan the liveness map and record where to relocate each indirection
  
  _Static_assert( sizeof( union zSlot ) % sizeof( uint64_t ) == 0, "slots are a multiple of uint64_t's" );
  
  uint64_t numLivemapChunks = ( livemapSlots * sizeof( union zSlot ) ) / sizeof( uint64_t ) ;
  
  uint64_t nextNewII = zNUM_UNIQUE_TYPES + 1 ;
  for(
    uint64_t * livemapChunk = (uint64_t *) livemap ;
    (uint64_t) ( livemapChunk - (uint64_t *) livemap ) < numLivemapChunks ;
    livemapChunk++
  ){
    if( *livemapChunk ){
      for(
        uint64_t bitIndex = 0 ;
        bitIndex < 8 ;
        bitIndex ++
      ){
        if( (*livemapChunk) & (1 << bitIndex) ){
          struct zII sourceII = 
            (struct zII){ .indirectionIndex = 
              ( (uint64_t) ( livemapChunk - (uint64_t *) livemap ) ) * 64 + bitIndex
            };
          
          rewrites[ sourceII.indirectionIndex ].index = nextNewII ;
          nextNewII ++ ;
        }
      }
    }
  }
  
  // now we have our rewrite table, we need to shift everything and rewrite their references
  
  uint64_t nextNewSlot = 0 ;
  for(
    uint64_t * livemapChunk = (uint64_t *) livemap ;
    (uint64_t) ( livemapChunk - (uint64_t *) livemap ) < numLivemapChunks ;
    livemapChunk ++
  ){
    if( *livemapChunk ){
      for(
        uint64_t bitIndex = 0 ;
        bitIndex < 8 ;
        bitIndex ++
      ){
        if( (*livemapChunk) & (1 << bitIndex) ){
          struct zII sourceII =
            (struct zII){ .indirectionIndex =
              ( (uint64_t) ( livemapChunk - (uint64_t *) livemap ) ) * 64 + bitIndex
            };
          
          // fprintf( stderr, "shifting %llu to %llu\n",
          //          (unsigned long long ) sourceII.indirectionIndex ,
          //          (unsigned long long ) rewrites[ sourceII.indirectionIndex ].index
          //        );
          
          // move indirection
          
          struct zIndirection * newIndirectionLocation = 
            zGc__indirection(
              gc,
              (struct zII){
                .indirectionIndex = 
                  rewrites[ sourceII.indirectionIndex ].index
              }
            );
          
          struct zIndirection * oldIndirectionLocation =
            zGc__indirection( gc, sourceII ) ;
          
          * newIndirectionLocation = * oldIndirectionLocation ;
          
          // move slotdata
          
          if( ! newIndirectionLocation->immediate && newIndirectionLocation->as_slotIndex.slotIndex != nextNewSlot ){
            char * destination = (char *) gc->slots[ nextNewSlot ].as_chardata ;
            char * source = (char *) gc->slots[ newIndirectionLocation->as_slotIndex.slotIndex ].as_chardata ;
            
            // a gc with no variable sized items will fail if these aren't ignorable
            zUNUSED( destination );
            zUNUSED( source );
            
            // 
            // !!! TYPESHIFTS increment nextNewSlot from within the type specific inclusions
            // 
            switch( newIndirectionLocation->objectType.objectType ){
              $TYPESHIFTS
              default:
              zGc__panic(
                "unknown type while shifting:: %llu\n",
                (unsigned long long) newIndirectionLocation->objectType.objectType
              );
            }  
          }
          
          // update references
          
          #define yield( ptr ) \
            do{ \
              (ptr)->indirectionIndex = rewrites[ (ptr)->indirectionIndex ].index ; \
            } while( 0 )
          
          switch( newIndirectionLocation->objectType.objectType ){
            $TYPEWALKS
            default:
              zGc__panic(
                "unknown type while rewriting :: %llu\n",
                (unsigned long long) newIndirectionLocation->objectType.objectType
              );
          }
          
          #undef yield
          
        }
      }
    }
  }
  
  // rewrite registers
  for(
    uint64_t registerIndex = 0 ;
    registerIndex < zNUM_REGISTERS ;
    registerIndex ++
  ){
    if( gc->registers[ registerIndex ].indirectionIndex > zNUM_UNIQUE_TYPES + 1 ){
      gc->registers[ registerIndex ].indirectionIndex =
        rewrites[ gc->registers[ registerIndex ].indirectionIndex ].index
        ;
    }
  }
  
  gc->nextII.indirectionIndex = finalDescentIndex + zNUM_UNIQUE_TYPES + 1 ;
  gc->nextSI.slotIndex        = nextNewSlot ;
  
  puts("");
  puts("post-collect");
  zGc__stats( gc );
  
  zGc__panic( "no, lol" );
}

static inline
struct zII
zGc__new(
  struct zGc * gc            ,
  struct zOT   objectType    ,
  size_t       requiredSpace
){
  
  uint64_t immediateBytes = sizeof( ((struct zIndirection){0}).as_immediateData ) ;
  
  uint64_t requiredIndirections = 1 ;
  uint64_t isImmediate = requiredSpace <= immediateBytes ;
  uint64_t requiredSlots =
    isImmediate
    ? 0
    : (requiredSpace / zSLOT_SIZE + ( !! (requiredSpace % zSLOT_SIZE) ) )
    ;
  
  uint64_t availableSlots =
    gc->numSlots
    - gc->nextII.indirectionIndex
    - gc->nextSI.slotIndex 
    ;
  
  uint64_t collectSlots = zGc__slots_needed_for_collection( gc, 1 + gc->nextII.indirectionIndex );
  
  if( requiredIndirections + requiredSlots + collectSlots > availableSlots ){
    zGc__collect( gc );
    
    uint64_t newAvailableSlots =
      gc->numSlots
      - gc->nextII.indirectionIndex
      - gc->nextSI.slotIndex
      ;
    
    if( requiredIndirections + requiredSlots + collectSlots > newAvailableSlots ){
      zGc__panic( "could not free sufficient space for requested allocation during gc collection" );
    }
    
  }
  
  struct zII newII = gc->nextII ;
  gc->nextII.indirectionIndex ++ ;
  
  struct zIndirection * indirection = zGc__indirection( gc, newII );
  indirection->objectType = objectType ;
  indirection->immediate  = isImmediate ;
  
  // fprintf( stderr, "II[%llu]@%p ot=%llu\n",
  //          (unsigned long long) newII.indirectionIndex ,
  //          indirection ,
  //          (unsigned long long) indirection->objectType.objectType
  //          );
  
  if( isImmediate ){
    memset( indirection->as_immediateData, 0, sizeof( indirection->as_immediateData ) );
  } else {
    indirection->as_slotIndex = gc->nextSI ;
    gc->nextSI.slotIndex += requiredSlots ;
  }
  
  return newII ;
}

$TYPEDEFINITIONS

#endif // ZGC_H include ward

"""

import sys

def main():
    specification = sys.stdin.readlines()
    
    KNOWN        = {}
    currentName  = None
    
    numRegisters = 1
    slotSize     = 8
    
    for line in specification:
        
        strippedLine = line.strip()
        
        if (not strippedLine) or strippedLine.startswith( '#' ):
            continue
        
        if ':' not in strippedLine:
            raise Exception( 'expected ":" in line %s' % repr( line ) )
        
        rawName, rawValue = strippedLine.split( ':', 1 )
        
        name = rawName.strip()
        value = rawValue.strip()
        
        if not name:
            raise Exception( 'expected name in line %s' % repr( line ) )
        
        if name == '@registers':
            numRegisters = int( value )
            continue
        
        if name == '@slotSize':
            slotSize = int( value )
            continue
        
        if name != 'name' and currentName == None:
            raise Exception( 'data before first name : %s' % repr( line ) )
        
        if name == 'name' and value in KNOWN:
            raise Exception( 'cannot redefine name : %s' % repr( name ) )
        
        if not value:
            raise Exception( 'expected value in line %s' % repr( line ) )
        
        if name == 'name':
            currentName = value
            KNOWN[ value ] = {
                'name' : value ,
                'eno'  : None  ,
            }
        else:
            if name in KNOWN[ currentName ]:
                raise Exception(
                    'cannot redefine attribute : %s' % repr( line )
                )
            
            KNOWN[ currentName ][ name ] = value
    
    uniqueTypes = [
        vv
        for vv in KNOWN.values()
        if vv.get( 'ctype', None ) == None and vv.get( 'type', None ) in [ None, 'Unique' ]
    ]
    
    uniqueTypeReservations = []
    maxUniqueEno = 0
    for eno, uniqueType in enumerate( uniqueTypes ):
        uniqueType['eno'] = eno + 1
        maxUniqueEno      = eno + 1
        
        uniqueTypeReservations.append(
            'static const struct zII zRESERVED_%(name)s = (struct zII){ .indirectionIndex = %(eno)s } ;' % {
                'name' : uniqueType['name'] ,
                'eno'  : eno + 1            ,
            }
        )
    
    typeEnumerations = []
    nextEno          = maxUniqueEno + 1
    for typeDefinition in sorted( KNOWN.values(), key = lambda ee : (ee['eno'] != None, ee['eno'], ee['name']) ):
        if typeDefinition['eno'] == None:
            typeDefinition['eno'] = nextEno
            nextEno += 1
        
        typeEnumerations.append(
            '#define zTYPE_%(name)s ((struct zOT) { .objectType = %(eno)s })' % (
                typeDefinition
            )
        )
    
    typeWalks = []
    for typeDefinition in sorted( KNOWN.values(), key = lambda ee : ee['eno'] ):
        if 'cwalk' in typeDefinition:
            typeWalks.append(
                ( 'case %(eno)s: '
                  '  do { '
                  '    typedef %(ctype)s type ; '
                  '    type * this = (type *) zGc__data( gc, (struct zII){ .indirectionIndex = rewrites[ currentDescentIndex ].index } ) ; '
                  '    { %(cwalk)s } '
                  '  } while(0) ; '
                  ' break; // %(name)s '
                ) % typeDefinition
            )
        else:
            typeWalks.append(
                'case %(eno)s: break ; // %(name)s' % typeDefinition
            )
    
    typeDefinitions = []
    for typeDefinition in sorted( KNOWN.values(), key = lambda ee : ee['eno'] ):
        
        if not typeDefinition.get( 'ctype', None ):
            # it's a unique type
            typeDefinitions.append(
              '// static error for %s ?' % repr( typeDefinition[ 'name' ] )
            )
            continue
            
        else:
            
            if typeDefinition.get( 'csize', None ) == None:
                if 'cmove' in typeDefinition:
                    raise Exception( 'cmove without csize?' )
                typeDefinition = typeDefinition.copy()
                typeDefinition.update({
                  'cvariableSize' : '0'              ,
                  'csize'         : 'sizeof( type )' ,
                  'cmove'         : 'sizeof( type )' ,
                })
            else:
                if 'cmove' not in typeDefinition:
                    raise Exception( 'csize without cmove?' )
                typeDefinition = typeDefinition.copy()
                typeDefinition.update({
                  'cvariableSize' : '1' ,
                })
            
            if typeDefinition.get( 'cargs', None ) == None:
                typeDefinition = typeDefinition.copy()
                typeDefinition.update({
                  'cargs' : ' ' ,
                })
            else:
                typeDefinition = typeDefinition.copy()
                typeDefinition.update({
                  'cargs' : ' , ' + typeDefinition['cargs'] ,
                })
            
            if typeDefinition.get( 'cinit', None ) == None:
                typeDefinition = typeDefinition.copy()
                typeDefinition.update({
                  'cinit' : '{}' ,
                })
            
            typeDefinitions.append(
              (
                'struct zII zGc__new_%(name)s ( struct zGc * gc %(cargs)s ) { \n'
                '  typedef %(ctype)s type ;\n'
                '  size_t requiredSpace = %(csize)s ;\n'
                '  struct zII new = zGc__new( gc, zTYPE_%(name)s, requiredSpace );\n'
                '  type * this = (type *) zGc__data( gc, new ); \n'
                '  zUNUSED( this ) ; // allow ignoring this in cinit \n'
                '  { %(cinit)s } \n'
                '  return new ; \n'
                '}\n'
              ) % (
                typeDefinition
              )
            )
    
    typeShifts = []
    for typeDefinition in sorted( KNOWN.values(), key = lambda ee : ee['eno'] ):
        if 'cmove' in typeDefinition:
            typeShifts.append(
                ( 'case %(eno)s: { '
                  '  typedef %(ctype)s type ; '
                  '  type * this = (type *) source ; '
                  '  uint64_t size = %(cmove)s ; '
                  '  memmove( destination, source, size ); '
                  '  nextNewSlot += size / zSLOT_SIZE + (!! (size %% zSLOT_SIZE)); '
                  '} '
                  'break; // %(name)s' 
                ) % (
                  typeDefinition
                )
            )
        else:
            typeShifts.append(
              'case %(eno)s: break; // %(name)s' % typeDefinition
            )
    
    template = TEMPLATE
    for name, replacement in [
      ('$NUMREGISTERS'      , str( numRegisters )) ,
      ('$TYPEENUMERATIONS'  , '\n'.join( typeEnumerations )),
      ('$TYPEWALKS'         , '\n'.join( typeWalks )),
      ('$TYPESHIFTS'        , '\n'.join( typeShifts )),
      ('$UNIQUETYPES'       , str( len( uniqueTypes ))),
      ('$OBJECTTYPES'       , str( len( KNOWN ))),
      ('$SLOTSIZE'          , str( slotSize )),
      ('$UNIQUERESERVATIONS', '\n'.join( uniqueTypeReservations )),
      ('$TYPEDEFINITIONS'   , '\n'.join( typeDefinitions )),
    ]:
      template = template.replace( name, replacement )
    
    print template
    print '//', repr( KNOWN )

if __name__ == '__main__':
    main()
