MODULE mo_control
! This module deals with output and control flags
!
! Miguel Garrido Zornoza 2024 
! mgarrizoraca@gmail.com
!
    implicit none

    ! Control flags *******************************************
    ! These are overwritten by the input command when running MOBILE (when namelist_inout is called)
    logical :: input    =.true.  ! (from flag) [Non-functional]
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
    logical :: out_D    =.true.  ! Output distance matrix for source

    ! 3D (x,y,t) Fields
    !
    !======= Disease
    logical :: out_S    =.true.  ! Susceptible
    logical :: out_E    =.true.  ! Exposed
    logical :: out_I    =.true.  ! Infected
    logical :: out_A    =.true.  ! Asymptomatic
    logical :: out_R    =.true.  ! Recovered
    !--- Cholera ----
    logical :: out_B    =.true.  ! Bacterial density (could be changed to generic source of disease, e.g., B, V,...)
    logical :: out_F    =.true.  ! Force of infection
    !--- Malaria ----
    logical :: out_EIR  =.true.  ! Entomological Inoculation Rate
    logical :: out_imm  =.true.  ! Endemicity level / Immunity
    !
    ! Defined in mo_vectri.f90
    !
    !======= Clima
    logical :: out_rain =.true.  ! Rainfall
    logical :: out_t2m  =.true. ! Air temperature

    !----------------------------------------------------------
    integer :: disID                 ! Disease ID (0: Cholera, 1: Malaria)
    character(len=100) :: run_name   ! Name of output files
    character(len=100) :: pop_file   ! Name of population file
    character(len=100) :: rain_file  ! Name of rain/precipitation file
    character(len=100) :: t2m_file   ! Name of temperature file
    character(len=100) :: area_file  ! Name of cell area file
    !----------------------------------------------------------

    ! https://fortran-lang.org/en/learn/quickstart/arrays_strings/#array-of-strings
    character(len=100) ::  time_names(1)= [character(len=20) :: "time"]
    character(len=100) ::  lon_names(3) = [character(len=20) :: "lon", "longitude", "X"]
    character(len=100) ::  lat_names(3) = [character(len=20) :: "lat", "latitude", "Y"]
    character(len=100) ::  pop_names(4) = [character(len=20) :: "pop", "population", "population density", "Band1"]
    character(len=100) ::  rain_names(5)= [character(len=20) :: "rain", "rainfall", "precipitation", "tp", "precip"]
    character(len=100) ::  temp_names(1)= [character(len=20) :: "temperature"]
    character(len=100) ::  area_names(1)= [character(len=20) :: "cell_area"]

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