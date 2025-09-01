#!/bin/bash

#export CPUPROFILE=$PWD/profile.prof
#export CPUPROFILE_FREQUENCY=${freq} # Sampling frequency (default is 100 per second)

while getopts "n:" flag; do
 case $flag in
   h) # Handle the -v flag
   # Display script help information
   usage
   exit 0
   ;;
   n) # Handle the -d flag
   output_name=$OPTARG
   ;;
   \?) # Handle invalid options
   usage
   exit 1
   ;;
 esac
done

prof_folder=${output_name}/profile
mkdir -p ${prof_folder}
# Run Google profiling tools

# brew install graphviz
# brew install gperftools

# CPU profiling flags --------------------
CPU=true            #   Main flag
            
#***************        Subflags (customise analysis)
text=true           # 
graph=true          #
interactive=false   #

# Heap profiling flags -------------------
heap=true
#-----------------------------------------

if ( ${CPU} ) ; then
    echo 'CPU profiling ; Functions and their contribution to CPU usage, sorted by time spent.'
    
    if ( ${text} ) ; then
        echo 'Text'
        pprof --text ${output_name}/mobile.out profile.prof > ${prof_folder}/profile.txt 2>/dev/null 
    fi

    if ( ${graph} ) ; then
        # Generate call graph
        echo 'Graph'
        pprof --dot ${output_name}/mobile.out profile.prof 2>/dev/null | dot -Tpng -o ${prof_folder}/callgraph.png
    fi

    if ( ${interactive} ) ; then
        echo 'Interactive [Non-functional]'
    fi

fi

if ( ${heap} ) ; then
    echo 'Heap Profiling ; Analyze memory allocation.'
    for dump in $(seq 1 1 13); do
        if ( ${text} ) ; then
            echo 'Text' ${dump}
            pprof --text ${output_name}/mobile.out heap_profile.*${dump}.heap > ${prof_folder}/heap_profile.*${dump}.txt 2>/dev/null 
        fi
        if ( ${graph} ) ; then
            echo 'Graph' ${dump}
                pprof --dot ${output_name}/mobile.out heap_profile.*${dump}.heap 2>/dev/null | dot -Tpng -o ${prof_folder}/heap_callgraph.${dump}.png
        fi
    done
fi
 
mv profile.prof ${prof_folder}  
mv *heap_profile* ${prof_folder}
# From ChatGPT -------------














