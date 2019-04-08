
# -g
flags = 
opt   = -O2
warns = -Wall -Wextra -Werror -Wmaybe-uninitialized -Wfatal-errors -fwhole-program

a.out:
	python gcgen.py <data/EXAMPLE >bld/OUT.c 
	gcc -g $(opt) -std=gnu99 $(warns) bld/OUT.c -o a.out

test:
	python gcgen.py <data/EXAMPLE >bld/OUT.c
	cat data/TEST.c >>bld/OUT.c
	gcc $(flags) $(opt) -E -std=gnu99 $(warns) bld/OUT.c -o bld/OUT.e
	gcc $(flags) $(opt) -S -std=gnu99 $(warns) bld/OUT.c -o bld/OUT.s
	gcc $(flags) $(opt) -std=gnu99 $(warns) bld/OUT.c -o a.out

profile:
	python gcgen.py <data/EXAMPLE >bld/OUT.c
	cat data/TEST.c >>bld/OUT.c
	echo compiling with profiling instrumentation in place >&2
	gcc -fprofile-generate -fprofile-dir=./bld/ $(flags) $(opt) -std=gnu99 $(warns) bld/OUT.c -o bld/a.out
	echo running ./bld/a.out -profile to generate profiling data in bld/ >&2
	./bld/a.out -profile
	echo compiling with profile information >&2
	gcc -fprofile-use -fprofile-dir=./bld/ $(flags) $(opt) -std=gnu99 $(warns) bld/OUT.c -o a.out

.PHONY: clean
clean:
	rm -f bld/*
	rm -f a.out
