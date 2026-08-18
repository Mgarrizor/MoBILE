# Makefile MoBILE
#
# Miguel Garrido Zornoza 2024
# mgarrizoraca@gmail.com
#
#=================
# Do not touch these lines!
.DELETE_ON_ERROR:                     # Delete target file if recipe has an error
.SUFFIXES:                            # No implicit rules
FC        := $(shell nf-config --fc)  # FORTRAN compiler (gfortran)
MAIN      := ./src/mobile.f90         # Main program file
SRC_DIR   := ./src      # Location of source code
DEPS_DIR  := ./src/deps # Location of dependency files
OBJ_DIR   := ./obj      # Location of objects (not in use right now)
BUILD_DIR := ./build    # Location to build the program
#-----------------------------------------
# Touch these lines if the nf-config shell command does not work for your system
INC_FLAGS := $(shell nf-config --fflags) # Flags needed to compile a FORTRAN program (NetCDF)
INC_LIBS  := $(shell nf-config --flibs) $(shell nc-config --libs) # Libraries needed to link a FORTRAN program (NetCDF)
PROF_LIB  := -L/opt/homebrew/opt/gperftools/lib -lprofiler -ltcmalloc  # Profiling library (Google performance tools)
#-----------------------------------------
# (https://stackoverflow.com/questions/3676322/what-flags-to-set-for-gfortran-compiler-to-catch-faulty-code)
# Build mode: make MODE=debug|normal|fast   (default normal)
#   debug  -Og + full runtime checks (-fcheck=all bounds-checks every array
#          reference). Measured 3.878 min CPU on the 1096-day Kenya run.
#   normal -O2 -ffp-contract=off, no runtime checks. WITH -ffp-contract=off
#          this is NUMERICALLY IDENTICAL TO debug: cdo diffn over the same
#          run reports max abs difference 0 on all 42 variables (the only
#          flagged records are NaN-vs-NaN in Vinf, which never compare
#          equal). Same run: 3.113 min CPU, ~20% cheaper than debug.
#          Without -ffp-contract=off, -O2 emits FMAs and the resulting 1-ULP
#          shifts flip agents across `generate_random() <= p` tests: measured
#          42682 of 47130 fields differing. That variant is 5% faster still,
#          but it is not reproducible -- do not use it for science.
#   fast   -O3 -ffast-math -march=native. UNTESTED here: neither its speed nor
#          whether it reproduces normal has been measured. -march=native also
#          ties the binary to this CPU. Verify both before using it.
MODE      ?= normal
COMMON    := -ffixed-line-length-none -ffree-line-length-512 -fopenmp
ifeq ($(MODE),debug)
  OPT     := -Og -fbacktrace -Wall -fcheck=all \
             -ffpe-summary=underflow,overflow $(COMMON)
else ifeq ($(MODE),fast)
  OPT     := -O3 -ffast-math -march=native $(COMMON)
else ifeq ($(MODE),normal)
  OPT     := -O2 -ffp-contract=off -fbacktrace $(COMMON)
else
  $(error MODE must be debug, normal or fast -- got '$(MODE)')
endif
EXE       := mobile.out # Name of executable file
#=========
# Coupling flag
# Conditional definition of COUPLING_FLAG
ifeq ($(ENABLE_COUPLING),1)
  COUPLING_FLAG := -cpp -DCOUPLED
else
  COUPLING_FLAG := -cpp
endif

# Mobility flag
# Conditional definition of MOBILITY_FLAG
ifeq ($(ENABLE_MOBILITY),1)
	MOBILITY_FLAG := -cpp -DMOBILITY
else
  MOBILITY_FLAG := -cpp
endif

#===== The following hierarchy will be created in the folder were is run
#
#         |-src (source code)
# build --
#         |-obj (objects and mod files)
#
# mobile.out
#
#=================================================

# Declare SOURCE files =======================
# Find all the f90 files we want to compile
# Note the single quotes around the * expressions. 
# The shell will incorrectly expand these otherwise, 
# but we want to send the * directly to the find command.
SRCS := $(shell find -L $(SRC_DIR) -name '*.f90')# -or -name '*.c')

# Filter out main file (mobile.f90) and then substitute suffix		
MOD1 := $(filter-out $(MAIN),$(SRCS))	
#MOD1:= $(FILTERED:%=$(BUILD_DIR)/%)
MOD2:= $(addprefix $(strip $(BUILD_DIR))/,$(MOD1:./src/%.f90=%.o))

MOD3:= $(addprefix $(strip $(BUILD_DIR))/,$(MOD1:./src/%.f90=%.mod))

DEPENDS := $(shell find -L $(DEPS_DIR) -name '*.d')
#MOD2:= $(MOD1:%.f90.o=%.f90.mod)
#=============================================

# Declare OBJECTS to be generated ============
# String substitution
# reference: https://www.gnu.org/software/make/manual/html_node/Text-Functions.html#Text-Functions
# Nomenclature: $(text:pattern=replacement)

#OBJS := $(SRCS:%=$(BUILD_DIR)/%.o)
#MOD  := $(SRCS:%=$(BUILD_DIR)/%.o)
OBJS := $(addprefix $(strip $(BUILD_DIR))/,$(SRCS:./src/%.f90=%.o))

# Runs last ------------------------------------
# - Does "nothing" but it actually generates the 
#   executable (.out) file by triggering the chain 
#   of rules written below
# Look for $(EXE)!

all: $(EXE)
	@echo 'Successful compilation'

# Runs third -----------------------------------
# Linking step
# - Requires object file of main
#   source file (mobile.f90), mobile.o

$(EXE): ./build/mobile.o
	@echo '2.- Link step'
	@$(FC) $(OBJS) -o $(EXE) $(INC_LIBS) $(PROF_LIB) $(OPT) 

# Runs second ----------------------------------
# - Generate main object file only if module object files or
#   main source file are newer than main object.
# - Look for module source files and module objects

./build/mobile.o: $(MOD2) $(MAIN)
	@echo '1.- Compile main' $(MAIN)
	@$(FC) -c $(MAIN) -I $(BUILD_DIR) -o $@ $(INC_FLAGS) $(OPT) $(COUPLING_FLAG) $(MOBILITY_FLAG)

# Runs first -----------------------------------
-include $(DEPENDS)

# - Compile module only if its .f90 source
#   file is newer than the corresponding
#   object file, $(MOD2). 
# - By including the above dependencies the module will 
#   also be recompiled if any dependency source file
#   is newer.

$(MOD2): ./build/%.o : ./src/%.f90 
	@echo '0.- Compile module' $<
	@mkdir -p $(BUILD_DIR)
	@$(FC) -cpp -c $< -J $(BUILD_DIR) -o $@ $(INC_FLAGS) $(OPT) $(COUPLING_FLAG) $(MOBILITY_FLAG)
# To generate dependency files add the flag -MD to the above command 
# ... -cpp -MD -c ...


.PHONY: clean   # Reconfigure how prerequisite for 'clean' target is treated
	            # i.e., always run 'make clean' even if a 'clean' file exists
clean:
	rm -rf ${DIR} *.o *.out




# ------------ BACKYARD ----------------------------
# DEFAULT Rule - Link ============
#$(BUILD_DIR)/$(TARGET_EXEC): $(OBJS)
#	$(FC) $(OBJS) -o $@ 
#=============================================
#$(TARGET_EXEC): $(OBJS) $(MODS)
#	@echo $(MODS)
#	$(FC) $(OBJS) -o $@
# BUILD STEP for f90 source ==================
# Prerequiste: src/<src_file_name>.f90 source files
# Target: build/<src_file_name>.f90.o

#@echo $(SRCS)
#@echo $(MOD1)
#@echo $(MOD2)

#$(filter %.o,$(obj_files))
# Compile modules
#%.mod: %.f90
#    $(FC) -c  $^

# Compile
#$(OBJS): $(SRCS)
#	@echo $(SRCS)
#	@echo $(OBJS)
#	mkdir -p $(BUILD_DIR)
#	$(FC) -I $(BUILD_DIR) -c $^ -J $(BUILD_DIR)
#	$(eval MODS := $(shell find $(BUILD_DIRS) -name '*.mod'))

#=============================================

# BUILD STEP for C source
#$(BUILD_DIR)/%.c.o: %.c
#	mkdir -p $(dir $@)
#	$(CC) $(CPPFLAGS) $(CFLAGS) -c $< -o $@



