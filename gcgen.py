
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
#include <time.h>

// abort on panic vs mere exit
#define zABORT 0
#define zWARNS 0

#define zMINSLOTS         5
#define zNUM_REGISTERS    $NUMREGISTERS
#define zNUM_UNIQUE_TYPES $UNIQUETYPES
#define zNUM_OBJECT_TYPES $OBJECTTYPES
#define zSLOT_SIZE        $SLOTSIZE

// define object type here and then determine the available immediate size based on it
// ( max of uint32, then question the user's sanity ? )
// ( or allow them to also specify a desired indirection size, which will allow manual control for wastage )

#define zSTRING( xx ) #xx
#define zSTRINGVALUE( xx ) zSTRING( xx )
#define zPASTE( xx, yy )  xx ## yy
#define zPASTEVALUE( xx, yy ) zPASTE( xx, yy )

#define zUNLIKELY(x) __builtin_expect((x),0)
#define zLIKELY(x) __builtin_expect((x),1)

#define zUNUSED(x) ((void)(x))

#define zGc__panic( pattern, ... ) do {                                                      \
    fprintf( stderr, "PANIC @ %s:%d :: " pattern "\n", __FILE__, __LINE__, ## __VA_ARGS__ ); \
    if( zABORT ){ abort(); }                                                                 \
    exit( 1 );                                                                               \
  } while(0);

#define zGc__warn( pattern, ... ) do {                                                        \
    if( zWARNS ){                                                                             \
      fprintf( stderr, "WARN @ %s:%d :: " pattern "\n", __FILE__, __LINE__, ## __VA_ARGS__ ); \
    }                                                                                         \
  } while(0);

#define zGc__log( pattern, ... ) do { \
    fprintf( stderr, "LOG @ %s:%d :: " pattern "\n", __FILE__, __LINE__, ## __VA_ARGS__ ); \
  } while(0);

struct zOT { uint16_t objectType ; };
struct zII { uint32_t indirectionIndex ; };
struct zSI { uint32_t slotIndex ; };

struct zLM { uint64_t index ; };

static const struct zII zRESERVED_NULL = (struct zII){ .indirectionIndex = 0 } ;
$UNIQUERESERVATIONS

// object type literals
// 
#define zOT_NULL ((struct zOT){ .objectType = 0 })
$TYPEENUMERATIONS

// typedefs
// 
$TYPEDEFS

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
  uint64_t            as_finalmapChunk            ;
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
  
  _Static_assert(
    zNUM_UNIQUE_TYPES + 1 < 64,
    "you have to update the OT generator to skip every 64th entry to avoid finalmap chunks"
  );
  
  _Static_assert(
    sizeof( union zSlot ) % sizeof( uint64_t ) == 0,
    "slots must be a multiple of uint64_t's"
  );
  
}

struct zGc {
  uint64_t    numSlots                     ; // how many total slots are available to the gc?
  
  uint64_t    remainingSlots               ; // number of slots left available to use
  uint64_t    collectionSlots              ; // number of slots needed to perform a collection
  
  struct zII  nextII                       ; // what is the index of the next indirection available to the gc?
  struct zSI  nextSI                       ; // what is the index of the next slot available to the gc?
  struct zII  registers [ zNUM_REGISTERS ] ; // root set
  
  uint64_t collections           ;
  uint64_t allocations           ;
  uint64_t bytesAllocated        ;
  uint64_t indirectionsAllocated ;
  uint64_t slotsAllocated        ;
  uint64_t indirectionShifts     ;
  uint64_t referenceRewrites     ;
  uint64_t slotShifts            ;
  uint64_t finalizers            ;
  
  // time kept in nanoseconds
  uint64_t longestGc ;
  uint64_t sumGc     ;
  
  union zSlot slots [] ; // gc'd data
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
struct zII
zGc__ii(
  struct zGc          * gc          ,
  struct zIndirection * indirection
){
  uint64_t index = gc->numSlots - ( (union zSlot *) indirection - gc->slots ) - 1 ;
  return (struct zII){ .indirectionIndex = index };
}

// see FINALMAP-NOTES
// 
static inline
uint64_t *
zGc__finalmap(
  struct zGc * gc ,
  struct zII   ii
){
  uint64_t chunkIndex = ii.indirectionIndex / 64 ;
  
  // note this isn't just undoing the /64, as the divisional integer
  // flooring puts each group of 64 items into the same slot, which
  // is what we desire. `v &= ~ 63` would also have worked, I suppose.
  // 
  uint64_t finalmapIndex = chunkIndex * 64 ;
  
  // and we're sewn through the indirections, so we're coming from the backend
  // we'll overlap with zOT_NULL, but that's okay. see note
  // 
  uint64_t slotIndex = gc->numSlots - 1 - finalmapIndex ;
  
  zGc__warn(
    "finalmap ii:%llu chunk:%llu index:%llu slot:%llu",
    (unsigned long long) ii.indirectionIndex ,
    (unsigned long long) chunkIndex          ,
    (unsigned long long) finalmapIndex       ,
    (unsigned long long) slotIndex
  );
  
  return & gc->slots[ slotIndex ].as_finalmapChunk ;
}

static inline
void
zGc__finalmap__zero(
  struct zGc * gc ,
  struct zII   ii
){
  zGc__warn( "zeroing" );
  * zGc__finalmap( gc, ii ) = 0 ;
}

static inline
uint32_t
zGc__finalmap__any_in_same_chunk(
   struct zGc * gc ,
   struct zII   ii
){
  zGc__warn( "checking finalmap chunk" );
  return !! * zGc__finalmap( gc, ii ) ;
}

static inline
void
zGc__finalmap__mark(
  struct zGc * gc ,
  struct zII   ii
){
  uint64_t bitIndex = ii.indirectionIndex % 64 ;
  
  zGc__warn(
    "marking ii:%llu bitIndex:%llu\n", (unsigned long long) ii.indirectionIndex, (unsigned long long) bitIndex
  );
  
  * zGc__finalmap( gc, ii ) |= ( 1llu << bitIndex ) ;
}

static inline
void
zGc__finalmap__unmark(
  struct zGc * gc ,
  struct zII   ii
){
  uint64_t bitIndex = ii.indirectionIndex % 64 ;
  
  zGc__warn(
    "unmarking ii:%llu bitIndex:%llu\n", (unsigned long long) ii.indirectionIndex, (unsigned long long) bitIndex
  );
  
* zGc__finalmap( gc, ii ) &= ~ ( 1llu << bitIndex ) ;
}

static inline
uint32_t
zGc__finalmap__marked(
  struct zGc * gc ,
  struct zII   ii
){
  uint64_t bitIndex = ii.indirectionIndex % 64 ;
  
  zGc__warn(
    "II[%llu] bit:0x%llx value:0x%llx",
    (unsigned long long) ii.indirectionIndex,
    (unsigned long long) bitIndex,
    (unsigned long long) * zGc__finalmap( gc, ii )
  );
  
  return !! ( (* zGc__finalmap( gc, ii )) & ( 1llu << bitIndex ) );
}

// </seeing FINALMAP-NOTES>

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
uint32_t
zGc__slots_needed_for_collection_livemaps(
  struct zGc * gc         ,
  uint32_t     numObjects
){
  zUNUSED( gc );
  // we only use 1 bit per object to track liveness
  uint64_t requiredSlots = ( ( numObjects / 64 ) / zSLOT_SIZE ) + 1 ;
  return requiredSlots ;
}

static inline
uint32_t
zGc__slots_needed_for_collection_rewrites(
  struct zGc * gc         ,
  uint32_t     numObjects
){
  zUNUSED( gc );
  uint64_t requiredSpace = numObjects * sizeof( struct zII ) ;
  
  // we could do a mod and only add 1 if not even, or we can just always add 1 and maybe waste a few bytes
  uint64_t requiredSlots = ( requiredSpace / zSLOT_SIZE ) + 1 ;
  
  return requiredSlots ;
}

static inline
uint32_t
zGc__slots_needed_for_collection(
  struct zGc * gc         ,
  uint32_t     numObjects
){
  zUNUSED( gc );
  uint32_t livemapSpace = zGc__slots_needed_for_collection_livemaps( gc, numObjects );
  uint32_t rewriteSpace = zGc__slots_needed_for_collection_rewrites( gc, numObjects );
  return livemapSpace + rewriteSpace ;
}

static inline
uint32_t
zGc__indirections_required_for_new(
  struct zGc * gc
){
  return 1 + !! ( gc->nextII.indirectionIndex % 64 == 0 ) ;
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
  zGc__log( "zgc::registers = %" PRIu32, zNUM_REGISTERS );
  zGc__log( "zgc::slots     = %" PRIu64, gc->numSlots ) ;
  zGc__log( "zgc::nextII    = II[%" PRIu32 "]", gc->nextII.indirectionIndex );
  zGc__log( "zgc::nextSI    = SI[%" PRIu32 "]", gc->nextSI.slotIndex );
  zGc__log( "" );
  
  zGc__log( "zgc::collections           = %" PRIu64 "", gc->collections           );
  zGc__log( "zgc::allocations           = %" PRIu64 "", gc->allocations           );
  zGc__log( "zgc::bytesAllocated        = %" PRIu64 "", gc->bytesAllocated        );
  zGc__log( "zgc::indirectionsAllocated = %" PRIu64 "", gc->indirectionsAllocated );
  zGc__log( "zgc::slotsAllocated        = %" PRIu64 "", gc->slotsAllocated        );
  
  zGc__log( "zgc::indirectionShifts     = %" PRIu64 "", gc->indirectionShifts     );
  zGc__log( "zgc::slotShifts            = %" PRIu64 "", gc->slotShifts            );
  zGc__log( "zgc::referenceRewrites     = %" PRIu64 "", gc->referenceRewrites     );
  zGc__log( "zgc::finalizersCalled      = %" PRIu64 "", gc->finalizers            );
  
  zGc__log( "zgc::longestGc             = %" PRIu64 "", gc->longestGc                          );
  zGc__log( "zgc::sumGc                 = %" PRIu64 "", gc->sumGc                              );
  zGc__log( "zgc::averageGc             = %" PRIu64 "", ( gc->sumGc / (gc->collections ? gc->collections : 1) ) );
  
  zGc__log( "" );
}

static inline
void
zGc__registers(
  struct zGc * gc
){
  zGc__warn( "zgc::registers (%" PRIu32 ")", (uint32_t)zNUM_REGISTERS );
  for( uint64_t rn = 0 ; rn < zNUM_REGISTERS ; rn++ ){
    zGc__warn( "  [%" PRIu64 "] :: II[%" PRIu32 "]", rn, zGc__get( gc, rn ).indirectionIndex );
  }
}

static inline
struct zGc *
zGc__create(
  size_t size
){
  
  if( size < sizeof( struct zGc ) ){
    zGc__panic( "size is insufficient to hold gc metadata structure" );
  }
  
  uint64_t numSlots = (size - sizeof( struct zGc )) / zSLOT_SIZE ;
  
  if( zUNLIKELY( numSlots < zMINSLOTS ) ){
    zGc__panic( "you cannot specify a gc of fewer than " zSTRINGVALUE( zMINSLOTS ) " SLOTS" );
  }
  
  char * start = mmap( NULL, size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0 );
  if( zUNLIKELY( start == MAP_FAILED ) ){
    zGc__panic( "failed to alloc memory for gc : %s", strerror( errno ) );
  }
  
  struct zGc * gc = (struct zGc *) start ;
  
  gc->numSlots = numSlots ;
  gc->nextII   = (struct zII) { .indirectionIndex = zNUM_UNIQUE_TYPES + 1 }; // 0 reserved for builtin zRESERVED_NULL
  gc->nextSI   = (struct zSI) { .slotIndex = 0 } ;
  
  gc->collections           = 0 ;
  gc->allocations           = 0 ;
  gc->bytesAllocated        = 0 ;
  gc->indirectionsAllocated = 0 ;
  gc->slotsAllocated        = 0 ;
  gc->indirectionShifts     = 0 ;
  gc->referenceRewrites     = 0 ;
  gc->slotShifts            = 0 ;
  gc->finalizers            = 0 ;
  
  gc->longestGc = 0 ;
  gc->sumGc     = 0 ;
  
  for( uint64_t index = 0; index < (zNUM_UNIQUE_TYPES + 1) ; index ++ ){
    struct zIndirection * indirection = zGc__indirection( gc, (struct zII){ .indirectionIndex = index });
    indirection->objectType.objectType = index ;
  }
  
  for( uint64_t index = 0; index < zNUM_REGISTERS ; index ++ ){
    zGc__set( gc, index, zRESERVED_NULL );
  }
  
  zGc__finalmap__zero( gc, (struct zII){ .indirectionIndex = 0 });
  
  return gc ;
}

static inline
void *
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
  uint64_t * lm    ,
  uint64_t   index
){
  uint64_t chunkIndex = index / 64 ;
  uint64_t bitIndex   = index % 64 ;
  
  // zGc__warn( "__mark %llu %llu", (unsigned long long) chunkIndex, (unsigned long long) bitIndex );
  // zGc__warn( "  pre:%llx", (unsigned long long) lm[ chunkIndex ] );
  
  lm[ chunkIndex ] |= (uint64_t) ( 1llu << bitIndex ) ;
  
  // zGc__warn( "  pst:%llx", (unsigned long long) lm[ chunkIndex ] );
}

static inline
unsigned char
zLM__marked(
  uint64_t * lm    ,
  uint64_t   index
){
  uint64_t chunkIndex = index / 64 ;
  uint64_t bitIndex   = index % 64 ;
  
  // zGc__warn( "__marked %llu %llu", (unsigned long long) chunkIndex, (unsigned long long) bitIndex );
  // zGc__warn( "  is :%llx", (unsigned long long) lm[ chunkIndex ] );
  
  return !! ( lm[ chunkIndex ] & (uint64_t) ( 1llu << bitIndex ) );
}

////

// mark that the given object requires finalization
// finalizing is marked during allocation and shifting
// 
static inline
void
zLM__mark_finalizing(
  uint64_t * lm    ,
  uint64_t   index
){
  uint64_t chunkIndex = index / 32 ;
  uint64_t bitIndex   = index % 32 ;
  
  lm[ chunkIndex ] |= (uint64_t) ( 1llu << ( bitIndex * 2llu + 1llu ) ) ;
}

// unmark that the given object requires finalization
// ( used when shifting objects around )
// 
static inline
void
zLM__unmark_finalizing(
  uint64_t * lm    ,
  uint64_t   index
){
  uint64_t chunkIndex = index / 32 ;
  uint64_t bitIndex   = index % 32 ;
  
  lm[ chunkIndex ] &= ~ (uint64_t) ( 1llu << ( bitIndex * 2llu + 1llu ) ) ;
}

static inline
void
zLM__marked_finalizing(
  uint64_t * lm    ,
  uint64_t   index
){
  uint64_t chunkIndex = index / 32 ;
  uint64_t bitIndex   = index % 32 ;
  
  lm[ chunkIndex ] |= (uint64_t) ( 1llu << ( bitIndex * 2llu + 1llu ) ) ;
}


static inline
void
zGc__dump(
  struct zGc * gc
){
  for( uint64_t jj = 0; jj < gc->nextII.indirectionIndex; jj++ ){
    zGc__warn( 
      "II[%llu] OT[%llu]",
      (unsigned long long) jj,
      (unsigned long long) zGc__indirection( gc, (struct zII){ .indirectionIndex = jj } )->objectType.objectType
    );
  }
}

// FINALMAP-NOTES
// 
// we're using every (ii%64==0)th indirection to store metadata on whether or not
// the indirections need to have finalizers called on them, so we can avoid scanning
// the entire bunch of them during garbage collection ( hoping to save time versus
// a full scan checking 64x bytes during collection, should test it the other way
// as well, but this seemed like a fun way to do it for now.
// we let use ii 0 for this as well, even though it's zOT_NULL, our stand in for
// no-value, because our no-value is just a reserved number and the ii itself never
// gets accessed by anything. just knowing it's being pointed to is sufficient
// information for anything needing to know if its II is zOT_NULL or not. the only
// mandatory unique type. that works out for us here.
// 
// so, following that little explanation, I've decided to create a helper function
// for incrementing the nextII value on the gc so it skips all of the (ii%64=0) entries
// while 0'ing them out along the way, so it's always safe for us to assume they
// contain a uint64_t bitfield of who needs to have finalizers called when they're
// being collected
// 
// this is used for take_next_ii, in __new, and for newNextII in __collect()
// it's responsible for renumbering all of the ii's. it returns the current value
// and increments, unless the current value is mod64=0, then it increments first
// to skip over those values
// 
// if doesn't bother with the skip when *counter is 0, since that slot is always
// the unique type zOT_NULL, and it doesn't use its data
// 
// the "zeroing_if_skipped" bit should hopefully get optimized out of all the callsites
// except in __new, where it's used to 0 out the finalmap. kind of ugly. probably
// should rework it in the future.
// 
static inline
uint32_t
zGc__take_and_increment_skipping_first_of_each_64_and_zeroing_if_skipped(
  uint32_t * counter    ,
  uint64_t * zeroOnSkip
){
  if( (*counter) && (*counter) % 64 == 0 ){
    (*counter) ++ ;
    if( zeroOnSkip ){
      * zeroOnSkip = 0 ;
    }
  }
  
  return (*counter) ++ ;
}

static inline
void
zGc__collect__mark_reserved_in_livemap(
  uint64_t * livemap
){
  // first mark all the reserved objects as live
  for( uint64_t jj = 0; jj < zNUM_UNIQUE_TYPES + 1; jj++ ){
    zLM__mark( livemap, jj );
  }
}

static inline
void
zGc__collect__push_registers_to_descent_array(
  struct zGc * gc                ,
  struct zII * rewrites          ,
  uint64_t *   livemap           ,
  uint32_t *   finalDescentIndex
){
  // first preload the descent array with whatevers in the current registers
  for( uint64_t registerIndex = 0 ; registerIndex < zNUM_REGISTERS ; registerIndex ++ ){
    if( ! zLM__marked( livemap, gc->registers[ registerIndex ].indirectionIndex ) ){
      rewrites[ (*finalDescentIndex)++ ].indirectionIndex 
        = gc->registers[ registerIndex ].indirectionIndex 
        ;
      zLM__mark( livemap, gc->registers[ registerIndex ].indirectionIndex );
    }
  }
}

static inline
void
zGc__collect__create_livemap(
  struct zGc * gc                ,
  struct zII * rewrites          ,
  uint64_t *   livemap           ,
  uint32_t *   finalDescentIndex
){
  // now we'll descend the current object heirarchy and create the livemap
  uint64_t currentDescentIndex = 0 ;
  while( currentDescentIndex < *finalDescentIndex ){
    struct zIndirection * indirection =
      zGc__indirection( gc, (struct zII){ .indirectionIndex = rewrites[ currentDescentIndex ].indirectionIndex } )
      ;
    
    // zGc__warn( 
    //   "descent/RW[%llu]=II[%llu]=[%p] ot=%llu",
    //   (unsigned long long) currentDescentIndex,
    //   (unsigned long long) rewrites[ currentDescentIndex ].indirectionIndex,
    //   indirection ,
    //   (unsigned long long) indirection->objectType.objectType
    // );
    
    #define yield( ptr ) \
      do{ \
        if(! zLM__marked( livemap, (ptr)->indirectionIndex ) ){ \
          if( (ptr)->indirectionIndex > zNUM_UNIQUE_TYPES ){ \
            rewrites[ (*finalDescentIndex)++ ].indirectionIndex \
              = (ptr)->indirectionIndex \
              ; \
            zLM__mark( livemap, (ptr)->indirectionIndex ); \
          } \
        } \
      } while (0)
    
    #define zTYPEWALK_PREFIX zSCAN
    
    #define zCURRENT_II (currentDescentIndex)
    
    // type walk targets
    // 
    $TYPEWALKTARGETS
    
    // type walks
    // 
    goto * zPASTEVALUE( zTYPEWALK_PREFIX, typeWalkTargets )[ indirection->objectType.objectType ];
    $TYPEWALKS
    zPASTEVALUE( zTYPEWALK_PREFIX, typeWalkExit ):;
    
    #undef zCURRENT_II
    #undef zTYPEWALK_PREFIX
    #undef yield
    
    currentDescentIndex ++ ;
  }
  
}

static inline
uint32_t
zGc__collect__create_rewrite_array(
  struct zGc * gc               ,
  uint64_t     numLivemapChunks ,
  struct zII * rewrites         ,
  uint64_t *   livemap
){
  (void) gc ;
  
  uint32_t nextNewII = 0 ;
  for(
    uint64_t * livemapChunk = (uint64_t *) livemap ;
    (uint64_t) ( livemapChunk - (uint64_t *) livemap ) < numLivemapChunks ;
    livemapChunk++
  ){
    if( *livemapChunk ){
      for(
        uint64_t bitIndex = 0 ;
        bitIndex < 64 ;
        bitIndex++
      ){
        if( (*livemapChunk) & (1llu << bitIndex) ){
          struct zII sourceII = 
            (struct zII){ .indirectionIndex = 
              ( (uint64_t) ( livemapChunk - (uint64_t *) livemap ) ) * 64 + bitIndex
            };
          
          rewrites[ sourceII.indirectionIndex ].indirectionIndex 
            = zGc__take_and_increment_skipping_first_of_each_64_and_zeroing_if_skipped(
                & nextNewII ,
                NULL
              );
        }
      }
    }
  }
  
  return nextNewII ;
}

static inline
void
zGc__finalize(
  struct zGc * gc ,
  struct zII   ii
){
  // zGc__warn(
  //   "finalize II[%llu] OT[%llu]",
  //   (unsigned long long) ii.indirectionIndex,
  //   (unsigned long long) zGc__indirection( gc, ii )->objectType.objectType
  // );
  
  #define zPREFIX zINLIVE
  #define zCURRENT_II (ii)
  
  static void * zInlineJumps [] = { && zINLIVEcFreeExit $CFREETARGETS } ;
  (void) zInlineJumps ;
  
  goto * zInlineJumps[ zGc__indirection( gc, ii )->objectType.objectType ];
  $CFREES
  zINLIVEcFreeExit:;
  
  #undef zPREFIX
  #undef zCURRENT_II
  
  zGc__finalmap__unmark( gc, ii );
  
  gc->finalizers ++ ;
}

static inline
void
zGc__collect__move_slot_data(
  struct zGc *          gc                     ,
  struct zIndirection * newIndirectionLocation ,
  uint32_t *            nextNewSlot            ,
  uint64_t *            slotShifts
){
  if( ! newIndirectionLocation->immediate && newIndirectionLocation->as_slotIndex.slotIndex != *nextNewSlot ){
    char * destination = (char *) gc->slots[ *nextNewSlot ].as_chardata ;
    char * source = (char *) gc->slots[ newIndirectionLocation->as_slotIndex.slotIndex ].as_chardata ;
    
    // a gc with no variable sized items will fail if these aren't ignorable
    zUNUSED( destination );
    zUNUSED( source );
    
    // 
    // !!! TYPESHIFTS increment nextNewSlot from within the type specific inclusions
    // !!! TYPESHIFTS increment slotShifts from within type specific inclusions
    // 
    
    $TYPESHIFTTARGETS
    
    goto * typeShiftTargets[ newIndirectionLocation->objectType.objectType ] ;
    $TYPESHIFTS
    typeShiftExit:;
  }
}

static inline
void
zGc__collect__update_references(
  struct zGc *          gc                     ,
  struct zII *          rewrites               ,
  struct zIndirection * newIndirectionLocation ,
  uint64_t *            referenceRewrites
){
  #define zTYPEWALK_PREFIX zREWRITE
  
  #define yield( ptr ) \
    do{ \
      (ptr)->indirectionIndex = rewrites[ (ptr)->indirectionIndex ].indirectionIndex ; \
      referenceRewrites ++ ; \
    } while( 0 )
  
  #define zCURRENT_II (zGc__ii( gc, newIndirectionLocation ).indirectionIndex)
  
  // type walk targets
  // 
  $TYPEWALKTARGETS
  
  // type walks
  goto * zPASTEVALUE( zTYPEWALK_PREFIX, typeWalkTargets )[ newIndirectionLocation->objectType.objectType ];
  $TYPEWALKS
  zPASTEVALUE( zTYPEWALK_PREFIX, typeWalkExit ) :;
  
  #undef zCURRENT_II
  #undef yield
  #undef zTYPEWALK_PREFIX
}

static inline
uint32_t
zGc__collect__compact_objects_and_rewrite_references(
  struct zGc *  gc                ,
  uint64_t      numLivemapChunks  ,
  struct zII *  rewrites          ,
  uint64_t *    livemap           ,
  
  uint64_t *    indirectionShifts ,
  uint64_t *    slotShifts        ,
  uint64_t *    referenceRewrites
){
  uint32_t nextNewSlot = 0 ;
  
  for(
    uint32_t chunkIndex = 0 ;
    chunkIndex < numLivemapChunks ;
    chunkIndex ++
  ){
    if( livemap[ chunkIndex ] ){
      
      zGc__warn( "hbb chunk:%llu", (unsigned long long) chunkIndex );
      
      // we always skip bitIndex = 0, since that's where our finalmap chunks are located
      // we'll skip zOT_NULL as well, but who cares since it's static and needs nothing done
      // 
      uint64_t bitIndex = 1 ;
      
      while( bitIndex < 64 ){
        
        unsigned calculatedIndex = chunkIndex * 64 + bitIndex ;
        struct zII sourceII = (struct zII){ .indirectionIndex = calculatedIndex };
        
        if( zLM__marked( livemap, sourceII.indirectionIndex ) ){
          
          // move indirection
          
          struct zIndirection * newIndirectionLocation =
            zGc__indirection(
              gc,
              (struct zII){
                .indirectionIndex = 
                  rewrites[ sourceII.indirectionIndex ].indirectionIndex
              }
            );
          
          struct zIndirection * oldIndirectionLocation =
            zGc__indirection( gc, sourceII ) ;
          
          // zGc__warn(
          //   "shifting %llu -> %llu ( %llu->objectType )" ,
          //   (unsigned long long) zGc__ii( gc, oldIndirectionLocation ).indirectionIndex ,
          //   (unsigned long long) zGc__ii( gc, newIndirectionLocation ).indirectionIndex ,
          //   (unsigned long long) oldIndirectionLocation->objectType.objectType
          // );
          
          if( newIndirectionLocation != oldIndirectionLocation ){
            * newIndirectionLocation = * oldIndirectionLocation ;
            indirectionShifts ++ ;
            
            if( zGc__finalmap__marked( gc, sourceII ) ){
              zGc__finalmap__unmark( gc, sourceII );
              zGc__finalmap__mark(
                gc,
                (struct zII){
                  .indirectionIndex = rewrites[ sourceII.indirectionIndex ].indirectionIndex
                }
              );
            }
          }
          
          // move slotdata
          
          if(
            (! newIndirectionLocation->immediate)
            &&
            ( newIndirectionLocation->as_slotIndex.slotIndex != nextNewSlot )
          ){
            zGc__collect__move_slot_data(
              gc                     ,
              newIndirectionLocation ,
              & nextNewSlot          ,
              slotShifts
            );
          }
          
          // update references
          
          zGc__collect__update_references(
            gc                     ,
            rewrites               ,
            newIndirectionLocation ,
            referenceRewrites
          );
          
          // </if livemap[ chunkindex ]>
          
        } else if( zGc__finalmap__marked( gc, sourceII ) ){
          zGc__finalize( gc, sourceII );
        }
        
        bitIndex ++ ;
      }
    } else if( zGc__finalmap__any_in_same_chunk( gc, (struct zII){ .indirectionIndex = chunkIndex * 64 } ) ){
      // the current chunk doesn't have anything alive in it,
      // but does have items that need to have finalizers called
      // on them before we're done with them
      // 
      
      zGc__warn( "hmm" );
      
      // 1 to skip the finalmap entry at 0
      uint32_t bitIndex = 1llu ;
      while( bitIndex < 64 ){
        struct zII target = (struct zII){ .indirectionIndex = chunkIndex * 64 + bitIndex } ;
        
        if( zGc__finalmap__marked( gc, target ) ){
          zGc__finalize( gc, target );          
        }
        
        bitIndex ++ ;
      }
      
      zGc__finalmap__zero( gc, (struct zII){ .indirectionIndex = chunkIndex * 64 } );
    }
  }
  
  return nextNewSlot ; 
}

static inline
uint64_t
zGc__now(
  void
){
  struct timespec spec ;
  clock_gettime( CLOCK_MONOTONIC, & spec );
  return (uint64_t) (spec.tv_sec) * 1000000000llu + (uint64_t) (spec.tv_nsec) ;
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
  
  // puts("");
  // puts("pre-collect");
  // zGc__stats( gc );
  // zGc__registers( gc );
  // zGc__dump( gc );
  
  uint64_t start = zGc__now();
  
  uint64_t livemapSlots = zGc__slots_needed_for_collection_livemaps( gc, gc->nextII.indirectionIndex );
  uint64_t rewriteSlots = zGc__slots_needed_for_collection_rewrites( gc, gc->nextII.indirectionIndex );
  
  // zGc__warn(
  //   "livemapSlots:%llu rewriteSlots:%llu "
  //   "rewrites(%p-%p) slots(%p-%p) registers(%p-%p) livemap(%p-%p) indirections(%p-%p)",
  //   (unsigned long long ) livemapSlots,
  //   (unsigned long long ) rewriteSlots,
  //   (struct zII *) & gc->slots[ gc->nextSI.slotIndex + livemapSlots ].as_chardata[0] ,
  //   (union zSlot *) & gc->slots[ gc->nextSI.slotIndex + livemapSlots ].as_chardata[0] 
  //     + rewriteSlots,
  //   gc->slots,
  //   gc->slots + gc->numSlots,
  //   gc->registers,
  //   gc->registers + zNUM_REGISTERS,
  //   (unsigned char *) & gc->slots[ gc->nextSI.slotIndex ].as_chardata[0] ,
  //   (unsigned char *) & gc->slots[ gc->nextSI.slotIndex ].as_chardata[0] + livemapSlots * sizeof( union zSlot ),
  //   zGc__indirection( gc, (struct zII){ .indirectionIndex = gc->nextII.indirectionIndex }),
  //   zGc__indirection( gc, (struct zII){ .indirectionIndex = 1 })
  // );
  
  uint64_t * livemap = (uint64_t *) & gc->slots[ gc->nextSI.slotIndex ].as_chardata[0] ;
  struct zII * rewrites = (struct zII *) & gc->slots[ gc->nextSI.slotIndex + livemapSlots ].as_chardata[0] ;
  
  memset( livemap, 0, livemapSlots * sizeof( union zSlot ) );
  memset( rewrites, 0, rewriteSlots * sizeof( struct zII ) );
  
  // we first use the rewrite array as a stack for live item descent
  // we'll keep track of what's alive in the livemap, which is a big fat bitmap
  
  // records how many live objects we come across, acts as index into descent array
  // 
  uint32_t finalDescentIndex = 0 ;
  
  zGc__collect__mark_reserved_in_livemap(
    livemap
  );
  
  zGc__collect__push_registers_to_descent_array(
    gc                  ,
    rewrites            ,
    livemap             ,
    & finalDescentIndex
  );
  
  zGc__collect__create_livemap(
    gc                  ,
    rewrites            ,
    livemap             ,
    & finalDescentIndex
  );
  
  // now we need to create to create a rewrite array, overwriting the descent array info
  //   previously stored into it
  // scan the liveness map and record where to relocate each indirection
  
  uint64_t numLivemapChunks =
    gc->nextII.indirectionIndex / 64
    + !! ( gc->nextII.indirectionIndex % 64 )
    ;
  
  uint32_t finalNewII =
    zGc__collect__create_rewrite_array(
      gc               ,
      numLivemapChunks ,
      rewrites         ,
      livemap
    );
  
  // now we have our rewrite table, we need to shift everything and rewrite their references
  
  uint64_t indirectionShifts = 0 ;
  uint64_t slotShifts        = 0 ;
  uint64_t referenceRewrites = 0 ;
  
  uint32_t nextNewSlot =
    zGc__collect__compact_objects_and_rewrite_references(
      gc                  ,
      numLivemapChunks    ,
      rewrites            ,
      livemap             ,
      
      & indirectionShifts ,
      & slotShifts        ,
      & referenceRewrites
    );
  
  // rewrite registers
  for(
    uint64_t registerIndex = 0 ;
    registerIndex < zNUM_REGISTERS ;
    registerIndex ++
  ){
    if( gc->registers[ registerIndex ].indirectionIndex > zNUM_UNIQUE_TYPES + 1 ){
      gc->registers[ registerIndex ].indirectionIndex =
        rewrites[ gc->registers[ registerIndex ].indirectionIndex ].indirectionIndex
        ;
    }
  }
  
  uint64_t stop = zGc__now();
  uint64_t total = stop - start ;
  
  gc->sumGc += total ;
  gc->longestGc = total > gc->longestGc ? total : gc->longestGc ;
  
  gc->indirectionShifts += indirectionShifts ;
  gc->slotShifts        += slotShifts        ;
  gc->referenceRewrites += referenceRewrites ;
  
  gc->nextII.indirectionIndex = finalNewII  ;
  gc->nextSI.slotIndex        = nextNewSlot ;
  
  gc->collections ++ ;
  
  // puts("");
  // puts("post-collect");
  // zGc__stats( gc );
  // zGc__registers( gc );
  // zGc__dump( gc );
}

static inline
int
zGc__has_sufficient_space_for_allocation(
  struct zGc * gc            ,
  uint32_t     requiredSlots
){
  uint64_t availableSlots =
    gc->numSlots
    - gc->nextII.indirectionIndex
    - gc->nextSI.slotIndex 
    ;
  
  uint64_t requiredIndirections =
    zGc__indirections_required_for_new( gc )
    ;
  
  uint64_t collectSlots =
    zGc__slots_needed_for_collection(
      gc                                                 ,
      gc->nextII.indirectionIndex + requiredIndirections 
    );
  
  return requiredIndirections + requiredSlots + collectSlots <= availableSlots ;
}

static inline
struct zII
zGc__new(
  struct zGc * gc            ,
  struct zOT   objectType    ,
  size_t       requiredSpace
){
  uint64_t immediateBytes = sizeof( ((struct zIndirection){0}).as_immediateData ) ;
  
  uint64_t isImmediate = requiredSpace <= immediateBytes ;
  uint64_t requiredSlots =
    isImmediate
    ? 0
    : (requiredSpace / zSLOT_SIZE + ( !! (requiredSpace % zSLOT_SIZE) ) )
    ;
  
  if( zUNLIKELY( ! zGc__has_sufficient_space_for_allocation( gc, requiredSlots ) ) ){
    zGc__collect( gc );
    
    if( zUNLIKELY( ! zGc__has_sufficient_space_for_allocation( gc, requiredSlots ) ) ){
      zGc__panic( "could not free sufficient space for requested allocation during gc collection" );
    }
  }
  
  struct zII newII = 
    (struct zII){
      .indirectionIndex =
        zGc__take_and_increment_skipping_first_of_each_64_and_zeroing_if_skipped(
          & gc->nextII.indirectionIndex ,
          zGc__finalmap( gc, gc->nextII )
        )
    };
  
  static unsigned char requiresFinalization [] = { 0 $ISCFREES } ;
  
  struct zIndirection * indirection = zGc__indirection( gc, newII );
  indirection->objectType = objectType ;
  indirection->immediate  = isImmediate ;
  
  if( requiresFinalization[ objectType.objectType ] ){
    zGc__finalmap__mark( gc, newII );
  }
  
  if( isImmediate ){
    memset( indirection->as_immediateData, 0, sizeof( indirection->as_immediateData ) );
  } else {
    indirection->as_slotIndex = gc->nextSI ;
    gc->nextSI.slotIndex += requiredSlots ;
    gc->slotsAllocated += requiredSlots ;
  }
  
  gc->bytesAllocated        += requiredSpace ;
  gc->indirectionsAllocated += 1 ; // don't count finalmaps
  gc->allocations ++ ;
  
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
    
    for entry in KNOWN.values():
        if entry.get( 'cfree', None ) == None:
            entry['iscfree'] = 0
        else:
            entry['iscfree'] = 1
    
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
            '#define zOT_%(name)s ((struct zOT) { .objectType = %(eno)s })' % (
                typeDefinition
            )
        )
    
    typedefs = []
    for typeDefinition in sorted( KNOWN.values(), key = lambda ee : ee['eno'] ):
        if 'ctype' in typeDefinition:
            typedefs.append(
                'typedef %(ctype)s zTYPE_%(name)s ; ' % typeDefinition
            )
    
    typeWalkTargets = []
    typeWalkTargets.append(
      'static void * zPASTEVALUE( zTYPEWALK_PREFIX, typeWalkTargets ) [] = { && zPASTEVALUE( zTYPEWALK_PREFIX, typeWalkExit ) '
    )
    for typeDefinition in sorted( KNOWN.values(), key = lambda ee : ee['eno'] ):
        if 'cwalk' in typeDefinition:
            typeWalkTargets.append(
              ' , && zPASTEVALUE( zTYPEWALK_PREFIX, typeWalkTargets_%(name)s ) ' % typeDefinition
            )
        else:
            typeWalkTargets.append(
              ' , && zPASTEVALUE( zTYPEWALK_PREFIX, typeWalkExit ) '
            )
    typeWalkTargets.append(
        ' } ; '
    )
    
    typeWalks = []
    for typeDefinition in sorted( KNOWN.values(), key = lambda ee : ee['eno'] ):
        if 'cwalk' in typeDefinition:
            typeWalks.append(
                ( 'zPASTEVALUE( zTYPEWALK_PREFIX, typeWalkTargets_%(name)s ): '
                  '  do { '
                  '    typedef zTYPE_%(name)s type ; '
                  # '    zGc__warn( '
                  # '      "II[%%llu]@%%p", '
                  # '       (unsigned long long) (zCURRENT_II), '
                  # '       zGc__indirection( gc, (struct zII){ .indirectionIndex = zCURRENT_II }) '
                  # '    ); '
                  # '    zGc__warn( "RW[%%llu]", '
                  # '      (unsigned long long) (rewrites[ zCURRENT_II ].indirectionIndex) '
                  # '    ); '
                  '    type * this = '
                  '      (type *) zGc__data( '
                  '        gc, '
                  '        (struct zII){ '
                  '          .indirectionIndex = '
                  '            rewrites[ zCURRENT_II ].indirectionIndex '
                  '        } '
                  '      ) '
                  '    ; '
                  '    (void) this ; '
                  '    { %(cwalk)s } '
                  '  } while(0) ; '
                  ' goto zPASTEVALUE( zTYPEWALK_PREFIX, typeWalkExit ) ; // %(name)s '
                ) % typeDefinition
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
                '  typedef zTYPE_%(name)s type ;\n'
                '  size_t requiredSpace = %(csize)s ;\n'
                '  struct zII new = zGc__new( gc, zOT_%(name)s, requiredSpace );\n'
                '  type * this = (type *) zGc__data( gc, new ); \n'
                '  zUNUSED( this ) ; // allow ignoring this in cinit \n'
                '  { %(cinit)s } \n'
                '  return new ; \n'
                '}\n'
              ) % (
                typeDefinition
              )
            )
    
    typeShiftTargets = []
    typeShiftTargets.append(
      'static void * typeShiftTargets [] = { && typeShiftExit '
    )
    for typeDefinition in sorted( KNOWN.values(), key = lambda ee : ee['eno'] ):
        if 'cmove' in typeDefinition:
            typeShiftTargets.append(
              ' , && typeShiftTarget_%(name)s ' % typeDefinition
            )
        else:
            typeShiftTargets.append(
              ' , && typeShiftExit '
            )
    typeShiftTargets.append(
        ' } ; '
    )
    
    typeShifts = []
    for typeDefinition in sorted( KNOWN.values(), key = lambda ee : ee['eno'] ):
        if 'cmove' in typeDefinition:
            typeShifts.append(
                ( 'typeShiftTarget_%(name)s: { '
                  '  typedef zTYPE_%(name)s type ; '
                  '  type * this = (type *) source ; '
                  '  uint64_t size = %(cmove)s ; '
                  '  memmove( destination, source, size ); '
                  '  nextNewSlot += size / zSLOT_SIZE + (!! (size %% zSLOT_SIZE)); '
                  '  slotShifts ++ ; '
                  '  goto typeShiftExit; '
                  '} '
                ) % (
                  typeDefinition
                )
            )
    
    iscfrees = []
    for typeDefinition in sorted( KNOWN.values(), key = lambda ee : ee['eno'] ):
        iscfrees.append(
          ', %d ' % typeDefinition['iscfree']
        )
    
    cfreeTargets = []
    for typeDefinition in sorted( KNOWN.values(), key = lambda ee : ee['eno'] ):
        if 'cfree' in typeDefinition:
            cfreeTargets.append(
                ' , && zPASTEVALUE( zPREFIX, cfreeTarget__%(name)s ) ' % typeDefinition
            )
        else:
            cfreeTargets.append(
                ' , && zPASTEVALUE( zPREFIX, cFreeExit ) '
            )
    
    cfrees = []
    for typeDefinition in sorted( KNOWN.values(), key = lambda ee : ee['eno'] ):
        if 'cfree' in typeDefinition:
            cfrees.append(
                (
                    'zPASTEVALUE( zPREFIX, cfreeTarget__%(name)s ): { \n'
                    '  typedef zTYPE_%(name)s type ; \n'
                    '  type * this = zGc__data( gc, zCURRENT_II ); \n'
                    '  (void) this ; \n'
                    '  %(cfree)s ; \n'
                    '  goto zPASTEVALUE( zPREFIX, cFreeExit ); \n'
                    '}\n'
                ) % typeDefinition
            )
    
    template = TEMPLATE
    for name, replacement in [
      ('$NUMREGISTERS'      , str( numRegisters )),
      ('$TYPEDEFS'          , '\n'.join( typedefs ) ),
      ('$TYPEENUMERATIONS'  , '\n'.join( typeEnumerations )),
      ('$TYPEWALKTARGETS'   , '\n'.join( typeWalkTargets )),
      ('$TYPEWALKS'         , '\n'.join( typeWalks )),
      ('$TYPESHIFTTARGETS'  , '\n'.join( typeShiftTargets )),
      ('$TYPESHIFTS'        , '\n'.join( typeShifts )),
      ('$UNIQUETYPES'       , str( len( uniqueTypes ))),
      ('$OBJECTTYPES'       , str( len( KNOWN ))),
      ('$SLOTSIZE'          , str( slotSize )),
      ('$UNIQUERESERVATIONS', '\n'.join( uniqueTypeReservations )),
      ('$TYPEDEFINITIONS'   , '\n'.join( typeDefinitions )),
      ('$ISCFREES'          , '\n'.join( iscfrees )),
      ('$CFREETARGETS'      , '\n'.join( cfreeTargets )),
      ('$CFREES'            , '\n'.join( cfrees )),
    ]:
      template = template.replace( name, replacement )
    
    print template
    print '//', repr( KNOWN )

if __name__ == '__main__':
    main()
