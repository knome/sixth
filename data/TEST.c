
#include <stdio.h>

int main(
  int argc     ,
  char ** argv 
){
  
  zUNUSED( argc );
  zUNUSED( argv );
  
  struct zGc * gc = zGc__create( 2000000 );
  if( ! gc ){
    printf( "failed to allocate a new gc\n" );
  }
  
  printf( "successfully allocated gc!\n" );
  
  zGc__stats( gc );
  
  // char * data = malloc( 500000 );
  // if( ! data ){
  //   puts( "nope" );
  //   exit(1);
  // }
  
  for(
    uint64_t wat = 0    ;
    wat < 1000000llu ;
    wat ++
  ){
    // char * ss = 
    //   "this is a test, this is only a test."
    //   " if this were an actual emergency,"
    //   " you'd be getting fired out of a cannon towards a space station by now. This is only a test" 
    // ;
    // struct zII newStringII = zGc__new_SmallString( gc, strlen( ss ), ss );
    // struct zII newStringII = zGc__new_String( gc, 500000, data );
    // (void) newStringII ;
    // zGc__set( gc, wat % 4, newStringII );
    
    // struct zII newII = zGc__new_TinyString1( gc, "a" );
    // uint64_t ri = 1 + wat++ % 7 ;
    // uint64_t si = 10 + wat % 8 ;
    // zGc__set( gc, ri, newII );
    // zGc__set( gc, si, newStringII );
    
    // struct zII newConsII = zGc__new_Cons( gc );
    // zTYPE_Cons * cons = zGc__data( gc, newConsII );
    // 
    // uint64_t ri    = wat % 20 ;
    // uint64_t riOff = wat % 20 ; // ( wat + 10 ) % 20 ;
    // 
    // cons->car = zGc__get( gc, riOff );
    // cons->cdr = zGc__get( gc, riOff );
    // 
    // zGc__set( gc, ri, newConsII );
    // zGc__set( gc, (ri + 1) % 20, zRESERVED_NULL );
    
    //zGc__new_Noise( gc );
    zGc__new_uint32( gc );
  }
  
  zGc__collect( gc );
  
  fprintf( stderr, "done\n" );
  zGc__stats( gc );
  
  return 0 ;
}
