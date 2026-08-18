MODULE mo_control
! This module deals with output and control flags
!
! Author: Miguel Garrido Zornoza (2024) 
! Contact: mgarrizoraca@gmail.com
!
    implicit none

    ! Control flags *******************************************
    ! These are overwritten by the input command when running MOBILE (when namelist_inout is called)
    logical :: input    =.true.  ! External population, driving files and model parameters
    logical :: agents   =.true.  ! Use agents, if false the program falls back to density
    logical :: coupling =.true. ! Use VECTRI
    logical :: gravity  =.true.  ! Use gravity model
    logical :: radial   =.false. ! If .true. build radial city, otherwise uniform 
    logical :: random   =.true.  ! Disease initialization - if .true. and rand_seed = .false. random S,I,A,R,B everywhere
                                 !                        - if .true. and rand_seed = .true.  f0 SIAR and random seed for B
                                 !                        - if .false. then f0 SIARB
    logical :: rand_seed=.false.  ! Disease initialization - if .true. random B at a seed and input S,I,A,R

    ! [Non-functional flags]
    logical :: network  =.false. ! Empirical network flag
    logical :: radiation=.false. ! Use radiation model
    logical :: diffusion=.false. ! Use diffusion model


    ! Output --------------------------------------------------
    ! 2D (x,y) Fields
    logical :: out_pop  =.true.   ! Output the steady-state human population density
    logical :: out_Q    =.true.   ! Output connectivity matrix for a given point ixy
    logical :: out_D    =.true.   ! Output distance matrix for source
    logical :: out_age  =.true.   ! Output age structure
    !
    ! 3D (x,y,t) Fields
    !
    !======= Agents
    logical :: out_N    =.true.  ! Agent field
    logical :: out_HA   =.true.  ! Human to agent ratio
    !
    !======= Disease
    logical :: diag_age =.true.  ! Create age-stratified diagnostics

    logical :: out_S       =.false.  ! Susceptible
    logical :: out_E       =.false.   ! Exposed
    logical :: out_I       =.false.   ! Infected
    logical :: out_Ia      =.false.   ! Age-disaggregated symptomatic (Ia)
    logical :: out_I_new   =.true.   ! New infections (I_new)
    logical :: out_Ia_new  =.true.   ! Age-disaggregated new infections (Ia_new)
    logical :: out_A       =.false.   ! Asymptomatic
    logical :: out_Aa      =.false.   ! Age-disaggregated asymptomatic (Aa)
    logical :: out_R       =.false.  ! Recovered

    !--- Cholera ----
    logical :: out_B    =.false.  ! Bacterial density (could be changed to generic source of disease, e.g., B, V,...)
    logical :: out_F    =.false.  ! Force of infection
    !--- Malaria ----
    logical :: out_EIR  =.true.  ! Entomological Inoculation Rate
    logical :: out_imm  =.true.  ! Endemicity level / Immunity
    logical :: out_imm_a=.true.   ! Age-disaggregated Immunity
    ! People per age block per cell. Ia/Aa/Ia_new/imm_a are all divided by
    ! N_a, so without it age-resolved output cannot be turned back into
    ! counts except by assuming every cell shares the national age structure.
    logical :: out_N_a  =.true.  ! Age-disaggregated population (N_a)
    logical :: out_hbr  =.false.  ! Human Biting Rate
    logical :: in_imm   =.false. ! Input immunity forcing flag: always false and automatically set to true is the corresponding
                                 ! forcing file is found.
    logical :: in_spinup =.false. ! True only while the spin-up loop (mobile.f90) is running --
                                  ! demographics (aging, births, deaths) are frozen during spin-up.
    !
    ! Defined in mo_vectri.f90
    !
    !======= Clima
    logical :: out_rain =.true.  ! Rainfall
    logical :: out_t2m  =.true. ! Air temperature

    !----------------------------------------------------------
    integer :: disID                 ! Disease ID (0: Cholera, 1: Malaria)
    character(len=100) :: run_name   ! Name of output files
    ! len=200 (not 100): these hold full file paths, which can exceed 100
    ! characters once a caller uses an absolute path a few directories deep
    ! (a Fortran namelist read silently truncates on overflow rather than
    ! erroring, so this must be sized generously up front).
    character(len=200) :: pop_file   ! Name of population file
    character(len=200) :: rain_file  ! Name of rain/precipitation file
    character(len=200) :: t2m_file   ! Name of temperature file
    character(len=200) :: area_file  ! Name of cell area file
    character(len=200) :: imm_file   ! Name of immunity forcing file
    character(len=200) :: mortality_file = '' ! Name of age-specific mortality-rate file; blank = scalar mu
    character(len=200) :: birthrate_file = '' ! Name of yearly birth-rate file; blank = scalar birth_rate
    character(len=200) :: mortality_time_file = '' ! Name of age-AND-year mortality-rate file; blank = use mortality_file/mu (age-only, whole-run)
    logical :: in_mortality_time = .false. ! True only if mortality_time_file was supplied -- gates the daily mu_age_today(:) update (see agents_pre_diagnostics)
    
    logical :: demog_counterfactual = .false. ! Counterfactual mode: the real simulation holds the age structure fixed at
                                              ! cumm_age.txt's shape while matching the growth the FACTUAL rates imply,
                                              ! instead of applying those rates to the agents directly. Set from &HUMAN
                                              ! (it belongs with the demographic-file settings, not &CONST's physical
                                              ! parameters). Requires at least one demographic rate file to be supplied.
                                              ! Resolved once in demog_init (mo_agents.f90) from demog_counterfactual
                                              ! plus which demographic files were actually given.
    integer, parameter :: DEMOG_STANDARD = 0 ! scalar mu/birth_rate
    integer, parameter :: DEMOG_FACTUAL  = 1 ! supplied files drive the real run
    integer, parameter :: DEMOG_COUNTER  = 2 ! "shadow"-derived g(t) drives the real run
    integer :: demog_mode = DEMOG_STANDARD
    character(len=200) :: namelist_filename
    !----------------------------------------------------------

    ! https://fortran-lang.org/en/learn/quickstart/arrays_strings/#array-of-strings
    character(len=100) ::  time_names(2)= [character(len=20) :: "time", "valid_time"]
    character(len=100) ::  lon_names(3) = [character(len=20) :: "lon", "longitude", "X"]
    character(len=100) ::  lat_names(3) = [character(len=20) :: "lat", "latitude", "Y"]
    character(len=100) ::  pop_names(4) = [character(len=20) :: "pop", "population", "population density", "Band1"]
    character(len=100) ::  rain_names(5)= [character(len=20) :: "rain", "rainfall", "precipitation", "tp", "precip"]
    character(len=100) ::  temp_names(2)= [character(len=20) :: "temperature","t2m"]
    character(len=100) ::  area_names(1)= [character(len=20) :: "cell_area"]
    character(len=100) ::  imm_names(2)= [character(len=20) :: "imm","imm_bulk"]

    ! Attribute names
    integer, parameter :: att_len = 6
    character(len=100) ::  att_names(att_len) = [character(len=50) :: "standard_name", "long_name", "units", "calendar", "axis", "cell_methods"]

    
    ! Define a derived type to hold either a string or a numeric value.
    type attribute_type
      character(len=50) :: str_value  ! Store the string representation
      logical :: is_numeric            ! Flag to indicate if it's numeric
      real :: num_value                ! Store the numeric value, if applicable
    end type attribute_type



    character(len=100) :: lon_att(att_len)
    character(len=100) :: lat_att(att_len)
    character(len=100) :: time_att(att_len)
    character(len=100) :: rain_att(att_len)


    ! Declare array of this derived type and initialize.
    !type(attribute_type), dimension(7) :: temp_att =[ &
    !         attribute_type(str_value="", is_numeric=.false., num_value=0.0), &
    !         attribute_type(str_value="", is_numeric=.false., num_value=0.0), &
    !         attribute_type(str_value="", is_numeric=.false., num_value=0.0), &
    !         attribute_type(str_value="", is_numeric=.false., num_value=0.0), &
    !         attribute_type(str_value="", is_numeric=.false., num_value=0.0), &
    !         attribute_type(str_value="", is_numeric=.false., num_value=0.0), &
    !         attribute_type(str_value="", is_numeric=.true.,  num_value=0.0)   ]

    character(len=100) :: temp_att(att_len)
    !----------------------------------------------------------



end MODULE mo_control