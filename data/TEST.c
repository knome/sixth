
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
  
  for(
    uint64_t wat = 0    ;
    wat < 1000000000llu ;
    wat ++
  ){
    struct zII newStringII = zGc__new_SmallString( gc, strlen( "hello world" ), "hello world" );
    zGc__set( gc, wat % 200000, newStringII );
    
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
  }
  
  fprintf( stderr, "done\n" );
  zGc__stats( gc );
  
  return 0 ;
}
