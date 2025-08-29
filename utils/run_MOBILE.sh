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
            disID=1          # 0: Cholera      -d
                             # 1: Malaria [non-functional]
                             # 2: Dengue  [non-functional]
            nstep=1095        # [days]       #  -n
            #nstep=500
            seed=12345                       #  -s
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
#           -v VECTRI          0: Inactive 1: Coupled
#           -i vectorID        0: Anopheles gambiae s. s. [Non-functional]
#                              1: An. funestus
#                              2: An. sacharovi     
#                             10: Aedes albopictus [Dengue non-functional]
#                             11: Ae. aegypti      [In development]
#           --------------------------------
            
            nagent=500000                 #  -a
            spin_up=0                     #  -u

            # Example path for test run (Senegal CHIRXS processed driving files 2012-2014)
            #rain_file=$MOBILE'/utils/test_run/rain.nc'  #  -r
            #pop_file=$MOBILE'/utils/test_run/pop.nc'    #  -p
            #temp_file=$MOBILE'/utils/test_run/t2m.nc'   #  -t
            #area_file=$MOBILE'/utils/test_run/area.nc'  #  -x


            rain_file='Data/CHIRXS/rainfall/Senegal/rain.nc'
            temp_file='Data/CHIRXS/temperature/Senegal/t2m.nc'
            pop_file='Data/CHIRXS/pop.nc'
            area_file='Data/CHIRXS/area.nc'  #  -x

            
            const='params.txt'            #  -c
            vectri=$disID
            vectorID=0         # [non-functional]

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
var_15="-x ${area_file}"

# HUMAN
var_10="-p ${pop_file}"
var_11="-a ${nagent}"

# CONST
var_12="-c ${const}"

# VECTRI
var_13="-v ${vectri}"
var_14="-i ${vectorID}"


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
$var_13
$var_15
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

