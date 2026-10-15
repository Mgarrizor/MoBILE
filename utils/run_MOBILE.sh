#!/bin/bash

# Script to run MOBILE
#
# Author: M. Garrido Zornoza
# Contact: mgarrizoraca@gmail.com

profiler=false     # Flag to profile model performance (time spent at each subroutine,... and memory usage at different simulation stages)
freq=110           # Sampling frequency for profiler (default is 100 per second)
parallel=true      # Flag to run MoBILE in parallel mode using Open MP

# Open MP parallelisation
if ( $parallel ) ; then
    echo '-- MoBILE being run in parallel mode --'
    export NPROC=$(getconf _NPROCESSORS_ONLN)
    export OMP_NUM_THREADS=$(getconf _NPROCESSORS_ONLN)
    export OMP_NUM_THREADS=4
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

            output_name='output'

#           -d Disease ID                       (0: Cholera ; 1: Malaria ; 2: Dengue [non-functional])
            disID=1
#           -s Seed for random number generator (reproducibility)
            seed=12345    
            name_list='namelist.nml'         
#          -------------------------------
#          |==============
#          |Optional flags:
#          |==============
            help=""  # Write -h if you need help 
#           -m Mobility flag (0 for now as mobility needs to be developed)
            mob=0
#           -n Number of integrated days [days] (If n = 0 then nsteps=lenght of driving fields)
            nstep=0

#           -a Number of agents 
            nagent=1000000

#           -u Spin Up (0: no spin-up ; 1: automatic spin-up to some tolerance) 
            spin_up=1

        # Kenya ============================

#           -p Population file 
            pop_file='path_to_pop_file/pop_file.nc'

#           -r Rainfall file 
            rain_file='path_to_rain_file/rain_file.nc'

#           -t Temperature file
            temp_file='path_to_temp_file/temp_file.nc'

#           -x Area file
            area_file='path_to_area_file/area_file.nc'
        # ===================================

#           -M Age-specific mortality-rate file (Optional; blank/NONE = scalar mu)
            mortality_file='NONE'
#           -B Time-varying birth-rate file (Optional; blank/NONE = scalar birth_rate)
            birthrate_file='NONE'
#           -c Constants/parameters file (example in params.txt)
            const='params.txt'
#           -v VECTRI          0: Inactive 1: Coupled
            vectri=$disID

#           -i Immunity forcing
         #   imm_forcing='experiments/imm_knockout/forcing/imm_bulk_counterfactual.nc'
            imm_forcing='NONE'

#           -?? vectorID        [Non-functional]
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
#          -i Vector ID       [Non-functional] --> for now we can only use the VECTRI default
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

var_00=${help}
var_01="${MOBILE}/mobile.sh"

# Flags in their namelist category
# INOUT
var_10="-o ${output_name}"
var_11="-d ${disID}"
var_12="-n ${nstep}"
var_13="-s ${seed}"
var_14="-u ${spin_up}"
var_15="-l ${name_list}"

# CLIMA
var_20="-r ${rain_file}"
var_21="-t ${temp_file}"
var_22="-x ${area_file}"

# HUMAN
var_30="-p ${pop_file}"
var_31="-a ${nagent}"
var_32="-i ${imm_forcing}"
var_33="-m ${mob}"
var_34="-M ${mortality_file}"
var_35="-B ${birthrate_file}"

# CONST
var_40="-c ${const}"

# VECTRI
var_50="-v ${vectri}"


read -r -d '' command << EOM
$var_00
$var_01

$var_10
$var_11
$var_12
$var_13
$var_14
$var_15

$var_20
$var_21
$var_22

$var_30
$var_31
$var_32
$var_33
$var_34
$var_35

$var_40

$var_50

EOM

echo ${command}
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

ncks -6 -O ${output_name}/${output_name}.nc ${output_name}/${output_name}'3.nc'

