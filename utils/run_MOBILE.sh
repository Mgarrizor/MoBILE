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
#          |===============
#          |Mandatory flags:
#           -o Output file name
#           -d Disease ID (Cholera: 0)
#           -n Number of integrated days
#           -s Seed for random number generator (reproducibility)
#           --------------------------------
            output_name='gravity'           #  -o
            disID=0          # 0: Cholera      -d
                             # 1: Malaria [non-functional]
                             # 2: Dengue  [non-functional]
            nstep=500        # [days]       #  -n
            seed=12345                      #  -s
#          |
#          |
#          |==============
#          |Optional flags:
#           -a Number of agents 
#           -u Spin Up 
#           -p Population file 
#           -r Rainfall file 
#           -t Temperature file
#           -c Constants/parameters file (example in params.txt)
#           -m Mobility file   [Non-functional]
#           -w Hydrology file  [Non-functional]

#           --------------------------------
            
            nagent=500000                 #  -a
            spin_up=0                     #  -u

            # Example path for test run (Senegal CHIRXS processed riving files 2012-2014)
            rain_file=$MOBILE'/utils/test_run/rain.nc'  #  -p
            pop_file=$MOBILE'/utils/test_run/pop.nc'    #  -r
            temp_file=$MOBILE'/utils/test_run/t2m.nc'   #  -t

            const='params.txt'            #  -c

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
var_7="-u ${spin_up}"

# CLIMA
var_8="-r ${rain_file}"
var_9="-t ${temp_file}"

# HUMAN
var_10="-p ${pop_file}"
var_11="-a ${nagent}"

# CONST
var_12="-c ${const}"

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
$var_12
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

