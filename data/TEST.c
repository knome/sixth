
#include <stdio.h>

void bump( void ){ fprintf( stderr, "\n" ); }

int main(
  int argc     ,
  char ** argv 
){
  
  zUNUSED( argc );
  zUNUSED( argv );
  
  struct zGc * gc = zGc__create( 2000000000 );
  if( ! gc ){
    printf( "failed to allocate a new gc\n" );
  }
  
  printf( "successfully allocated gc!\n" );
  
  zGc__stats( gc );
  bump();
  
  zGc__set( gc, 0, zRESERVED_NULL );
  
  zGc__set( gc, 9, zRESERVED_Mu );
  
  zGc__stats( gc );
  
  uint64_t wat = 0 ;
  while(1){
    // struct zII newII = zGc__new_SmallString( gc, strlen( "hello world" ), "hello world" );
    struct zII newII = zGc__new_TinyString1( gc, "a" );
    uint64_t ri = 1 + wat++ % 7 ;
    zGc__set( gc, ri, newII );
  }
  
  return 0 ;
}
