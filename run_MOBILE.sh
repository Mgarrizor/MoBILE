#!/bin/bash

profiler=false
freq=110
# Script to run MOBILE
export NPROC=$(getconf _NPROCESSORS_ONLN)
#export OMP_NUM_THREADS=$(getconf _NPROCESSORS_ONLN)
export OMP_NUM_THREADS=1
#export NPROC=2
#echo 'Number of processors =' ${NPROC}
#echo 'Number of threads = ' ${OMP_NUM_THREADS}

if ( $profiler ) ; then
    export CPUPROFILE=$PWD/profile.prof
    export CPUPROFILE_FREQUENCY=${freq} # Sampling frequency (default is 100 per second)
    export HEAPPROFILE=$PWD/heap_profile
fi

#echo $NPROC
# Flags:
#--------------------------------
# -h Help! [Non-functional]
#          | 
#          |
#          |Mandatory flags:
#           -o Output file name
#           -d Disease ID (Cholera: 0)
#           -n Number of integrated days
#           -s Seed for random number generator (reproducibility)
#           --------------------------------
            output_name='gravity'
            disID=0          # 0: Cholera
            nstep=2500       # [day]
            seed=12345
#          |
#          |
#          |
#          |Optional flags:
#           -a Number of agents 
#           -u Spin Up 
#           -p Population file 
#           -r Rainfall file 
#           -c Constants/parameters file 
#           -m Mobility file   [Non-functional]
#           -w Hydrology file  [Non-functional]

#           --------------------------------
            spin_up=0
            nagent=1500000
     #       pop_file='data/Italy/pop.nc'   # Italy
            rain_file='data/Italy/rain.nc'

     #       pop_file='data/Yemen/pop.nc'    # Yemen

            pop_file='data/Haiti/pop.nc'    # Haiti

            const='params.txt'

# Environmental variables
#--------------------------------
# - $MOBILE

# Variable list - to leave out a flag comment out the corresponding variable
#----------------

#var_1="-h" 
var_2="${MOBILE}/mobile.sh"

# INOUT
var_3="-o ${output_name}"
var_4="-d ${disID}"
var_5="-n ${nstep}"
var_6="-s ${seed}"

var_11="-u ${spin_up}"

# CLIMA
#var_7="-r ${rain_file}"

# HUMAN
var_8="-p ${pop_file}"
var_9="-a ${nagent}"

# CONST
var_10="-c ${const}"

read -r -d '' command << EOM
$var_1
$var_2
$var_3
$var_4
$var_5
$var_6
$var_7
$var_8
$var_9
$var_10
$var_11
EOM

echo 'Command:' ${command} > ${output_name}.info
echo 'Version:' >> ${output_name}.info
echo 'Retrieved from:' >> ${output_name}.info
echo 'Date:' $(date) >> ${output_name}.info

#---------------
# Run MOBILE

bash $command

#---------------

if ( $profiler ) ; then
    bash profiler.sh -n ${output_name}
fi
#--------------------------------

