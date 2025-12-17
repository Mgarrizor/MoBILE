#!/bin/bash
#
# Running MOBILE
# This file links the Makefile and source files of the program to the local folder,
# compiles the program and executes it. It will create a 'build' folder where one
# can find the object and mod files. 

# Index ------------------------
# A) Read flags
# 0) Prepare folder to save simulation
# 1) Link Makefile and src folder
# 2) Compile program
# 3) Create NAMELIST
# 4) Execute MOBILE
#-------------------------------

# A) Read flags

usage() { echo "Usage:              \n
                -o: Output filename [String]  \n
                -p: Path to population file [String] (Optional) \n
                -r: Path to rainfall file [String] (Optional) \n
                -t: Path to temperature file [String] (Optional) \n
                -d: Disease ID (0: Cholera) [Integer] \n
                -n: Number of integration steps (days) [Integer <= length of forcing files] \n
                -s: Seed [Integer] \n
                -a: Number of agents [Integer] \n
                -u: Spin up [0: no SI ; 1: SU to threshold] \n
                -v: VECTRI coupling [0: No, 1: Yes] \n
                -?: Vector ID [0: gambiae, ...] \n
                -x: Area of grid cells \n
                -i: Immunity forcing file \n

                 "; }
# Resources
# https://stackoverflow.com/questions/16483119/an-example-of-how-to-use-getopts-in-bash
# https://serverfault.com/questions/266867/bash-getops-allow-but-not-require-arg
while getopts ":ho:p:r:t:d:n:m:s:a:c:u:v:x:i:l:" flag; do
 case $flag in
   h) # Handle the -h flag
   # Display script help information
   usage
   exit 0
   ;;
   o) # Handle the -o flag
   filename=$OPTARG
   ;;
   p) # Handle the -p flag
   pop_file=$OPTARG
   ;;
   r) # Handle the -r flag
   rain_file=$OPTARG
   ;;
   t) # Handle the -t flag
   temp_file=$OPTARG
   ;;
   d) # Handle the -d flag
   disID=$OPTARG
   ;;
   n) # Handle the -n flag
   nstep=$OPTARG
   ;;
   m) # Handle the -m flag
   mob=$OPTARG
   ;;
   s) # Handle the -s flag
   seed=$OPTARG
   ;;
   a) # Handle the -a flag
   nagent=$OPTARG
   ;;
   c) # Handle the -c flag
   const=$OPTARG
   ;;
   u) # Handle the -u flag
   spin_up=$OPTARG
   ;;
   v) # Handle the -v flag
   vectri=$OPTARG
   ;;
   x) # Handle the -x flag
   area_file=$OPTARG
   ;;
   l) # Handle the -x flag
   name_list=$OPTARG
   ;;
   #i) # Handle the -i flag -> argument is not required (no colon after the 'i' flag)
   #imm_file=$OPTARG
   i)
   # This case handles '-i ""', which passes an empty string
   if [ "$OPTARG" = "NONE" ]; then # if the string has zero length then
     imm_file=""
   # This case handles '-i "my_string"'
   else
     imm_file="$OPTARG"
   fi
   ;;
   \?) # Handle invalid options
   usage
   exit 1
   ;;
 esac
done

# 0) Prepare folder to save simulation and namelist options

path=$PWD/$filename
namelist=$name_list

# If you are trying to run MOBILE in the root stop simulation
# Useful for GitHub development.

if [[ $PWD == *${MOBILE}* ]]; then # If PWD contains ${MOBILE} stop 
  echo 'Running MOBILE in root ; Stop.'
  exit 1
fi

mkdir -p $path

# 1) Link Makefile and src folder
# https://www.man7.org/linux/man-pages/man1/ln.1.html
ln -sf ${MOBILE}/Makefile ${path}
ln -sf ${MOBILE}/src ${path}

# If VECTRI is coupled then create symbolic links 
# pointing to the necessary files from VECTRI.
# These files will then be found and compiled by the Makefile

if [[ ${vectri} == 1 ]]; then
  echo '================= VECTRI active =================='

  touch "${path}/src/mo_netcdf.f90" # Touch file so that it is recompiled WITH the VECTRI lines

                                                                # These are the necessary VECTRI source files to
  #ln -sf ${VECTRI}/source/mo_constants.f90 ${path}/src         # couple it to the AB model.
  #ln -sf ${VECTRI}/source/mo_advect.f90 ${path}/src
  ln -sf ${MOBILE}/utils/vectri/mo_constants.f90 ${path}/src
  ln -sf ${MOBILE}/utils/vectri/mo_advect.f90 ${path}/src
  ln -sf ${MOBILE}/utils/vectri/mo_methods.f90 ${path}/src
  #-------------------------------------------------------------------------------------------------------------------

  ln -sf ${MOBILE}/utils/vectri/mo_vectri.f90  ${path}/src     # This is the file that declares, allocates and 
                                                               # initializes VECTRI's fields and wraps all subroutines 
                                                               # necessary for integrating the vector density.
                                                               # This module is NOT part of VECTRI.
  #-------------------------------------------------------------------------------------------------------------------

  ln -sf ${MOBILE}/utils/vectri/mo_vectri.d ${path}/src/deps   # Dependency files to ensure right compilation order.
  ln -sf ${MOBILE}/utils/vectri/mo_methods.d ${path}/src/deps  

  #-------------------------------------------------------------------------------------------------------------------

elif  [[ ${vectri} == 0 ]]; then
  echo '================= VECTRI inactive ================'

  # Remove symbolic links (present if running a second simulation in the same folder)
  if [[ -f "${path}/src/mo_vectri.f90" ]]; then
    rm "${path}/src/mo_vectri.f90"
    rm "${path}/src/mo_methods.f90"
    rm "${path}/src/mo_constants.f90"
    rm "${path}/src/mo_advect.f90"

    rm "${path}/src/deps/mo_vectri.d"
    rm "${path}/src/deps/mo_methods.d"

    touch "${path}/src/mo_netcdf.f90"    # Touch file so that it is recompiled withOUT the VECTRI lines

  fi
else
  echo '<<vectri>> flag should be either 0 or 1! --> Stopping simulation'
  exit 1
fi
#

if [[ ${mob} == 1 ]]; then
  echo '================= MOBILITY active ================'
elif [[ ${mob} == 0 ]]; then
  echo '================= MOBILITY inactive ================'
  if [[ ${disID} == 0 ]]; then
    echo 'Cholera needs mobility to eb active ; set mob = 1 --> Stopping simulation'
    exit 1
  fi
else
  echo '<<mob>> flag should be either 0 or 1! --> Stopping simulation'
  exit 1
fi
#-------------------------------
#
bash fetch_age.sh # Create age weights 
#
# 2) Compile program
(cd $path && make ENABLE_COUPLING=${vectri} ENABLE_MOBILITY=${mob})
exit=$? # Save exit status of 'make'.

# $? = Exit status of last executed command 

# For BASH, zero means a successful execution, while non-zero values are 
# mapped to different numbers depending on the exit reason. Exit statuses 
# fall between [0,255].
# (https://www.gnu.org/software/bash/manual/html_node/Exit-Status.html)

# For MAKE the exit status is always 0,1 or 2. 0 again means success.
# (https://www.gnu.org/software/make/manual/html_node/Running.html)

# "0: The exit status is zero if make is successful. 
#  2: The exit status is two if make encounters any errors. 
#     It will print messages describing the particular errors. 
#  1: The exit status is one if you use the ‘-q’ flag and 
#     make determines that some target is not already up to date."

if [ $exit != 0 ]; then
  echo "Makefile not successful" " --> Exit status:" $exit  
  exit 1
fi
#-------------------------------

lines=$(<"$const")  # < reads the entire content of the file into the variable "lines"
#echo $lines
# 3) Create NAMELIST
# https://cyber.dabamos.de/programming/modernfortran/namelists.html
cat << EOM > ${namelist}
! Program NAMELIST
! See: https://cyber.dabamos.de/programming/modernfortran/namelists.html
&INOUT
run_name='${filename}',
disID=${disID},
nsteps=${nstep},
seed=${seed},
spin_up=${spin_up}
/
&CLIMA
rain_file='${rain_file}',
t2m_file='${temp_file}',
area_file='${area_file}'
/
&HUMAN
pop_file='${pop_file}',
nagent=${nagent},
imm_file='${imm_file}',
/
&CONST
${lines}
/
EOM

# 4) Execute MOBILE (mobile.out)
echo '================= Running MoBILE ================='
${path}/mobile.out ${namelist}     # Pass namelist name as command line argument
#-------------------------------
mv ${namelist} ${filename}.nc ${filename}.info ${filename}/
cp $const ${filename}/

