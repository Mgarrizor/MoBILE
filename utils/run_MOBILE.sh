#!/bin/bash

# Script to run MOBILE

profiler=false     # Flag to profile model performance (time spent at each subroutine,... and memory usage at different simulation stages)
freq=110           # Sampling frequency for profiler (default is 100 per second)
parallel=true      # Flag to run MoBILE in parallel mode using Open MP

# Open MP parallelisation
if ( $parallel ) ; then
    echo '-- MoBILE being run in parallel mode --'
    export NPROC=$(getconf _NPROCESSORS_ONLN)
    export OMP_NUM_THREADS=$(getconf _NPROCESSORS_ONLN)
    #export OMP_NUM_THREADS=3
    #export NPROC=1
    echo 'Number of available processors =' ${NPROC}
    echo 'Number of used threads = ' ${OMP_NUM_THREADS}
    echo '---------------------------------------'
else
    echo '-- MoBILE being run in serial mode --'
    export OMP_NUM_THREADS=1
fi

# Profiler
if ( $profiler ) ; then
    export CPUPROFILE=$PWD/profile.prof
    export CPUPROFILE_FREQUENCY=${freq} 
    export HEAPPROFILE=$PWD/heap_profile
fi

# ======================= FLAGS ==========
# ----------------------------------------
# -h Help! [Non-functional]
#          ------------------------------- 
#          |===============
#          |Mandatory flags:
#          |===============
#           -o Output file name
            output_name='gravity'
#           -d Disease ID                       (0: Cholera ; 1: Malaria ; 2: Dengue [non-functional])
            disID=1 
#           -s Seed for random number generator (reproducibility)
            seed=12345             
#          -------------------------------
#          |==============
#          |Optional flags:
#          |==============
#           -n Number of integrated days [days] (If n = 0 then nsteps=lenght of driving fields)
            nstep=1096
#           -a Number of agents 
            nagent=500000     
#           -u Spin Up (0: no spin-up ; 1: automatic spin-up) 
            spin_up=0
#           -p Population file 
            pop_file='Data/CHIRXS/pop.nc'
#           -r Rainfall file 
            rain_file='Data/CHIRXS/rainfall/Senegal/rain.nc'
#           -t Temperature file
            temp_file='Data/CHIRXS/temperature/Senegal/t2m.nc'
#           -x Area file
            area_file='Data/CHIRXS/area.nc'
#           -c Constants/parameters file (example in params.txt)
            const='params.txt'
#           -v VECTRI          0: Inactive 1: Coupled
            vectri=$disID
#           -i vectorID        [Non-functional]
#                               -- Anophelines --
            vectorID=0       # 0: An. gambiae s. s. 
#                              1: An. funestus
#                              2: An. sacharovi
#                                 -- Aedes --     
#                             10: Ae. albopictus [Dengue non-functional]
#                             11: Ae. aegypti    [Dengue --> in development]

#           -d vectorDis       [Non-functional]
            vectorDis=0       

#          -------------------------------
#          |==============
#          Future developments
#          |==============
#          -d Vector disease  [Non-functional] (Dengue + Yellow Fever?)
#          -m Mobility file   [Non-functional]
#          -w Hydrology file  [Non-functional]
#          --------------------------------

#          --------------------------------
            # Example path for test run (Senegal CHIRXS processed driving files 2012-2014)
            #rain_file=$MOBILE'/utils/test_run/rain.nc'  #  -r
            #pop_file=$MOBILE'/utils/test_run/pop.nc'    #  -p
            #temp_file=$MOBILE'/utils/test_run/t2m.nc'   #  -t
            #area_file=$MOBILE'/utils/test_run/area.nc'  #  -x

# Environmental variables
#--------------------------------
# - $MOBILE

# Variable list - to leave out a flag comment out the corresponding variable
#----------------

#var_1="-h" 
var_2="${MOBILE}/mobile.sh"

# Flags in their namelist category
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
echo 'Retrieved from:' $(git -C ${MOBILE} remote get-url origin) >> ${output_name}.info
echo 'Date:' $(date) >> ${output_name}.info

#----------------
# == Run MoBILE =

bash $command

#----------------
# == Profiler ===
if ( $profiler ) ; then
    bash profiler.sh -n ${output_name}
fi
#--------------------------------

