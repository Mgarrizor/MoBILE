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
    logical :: agents   =.true.  ! Use agents, if false the program falls back to classic SIARB
    logical :: vectri   =.false. ! Use VECTRI [Non-functional]
    logical :: radial   =.true.  ! If .true. build radial city, otherwise uniform 
    logical :: network  =.false. ! Empirical network flag [Non-functional]
    logical :: gravity  =.true.  ! Use gravity model
    logical :: radiation=.false. ! Use radiation model [Non-functional]
    logical :: random   =.true.  ! Disease initialization - if .true. random S,I,A,R,B everywhere
    logical :: rand_seed=.false. ! Disease initialization - if .true. random B at a seed and input S,I,A,R

    ! Output --------------------------------------------------
    ! 2D (x,y) Fields
    logical :: out_pop  =.true.   ! Output the steady-state human population density
    logical :: out_Q    =.true.   ! Output connectivity matrix for a given point ixy
    logical :: out_D    =.false.  ! Output distance matrix for source

    ! 3D (x,y,t) Fields
    !
    ! Disease
    logical :: out_S    =.true.  ! Susceptible
    logical :: out_E    =.false. ! Exposed [Non-functional]
    logical :: out_I    =.true.  ! Infected
    logical :: out_A    =.true.  ! Asymptomatic
    logical :: out_R    =.true.  ! Recovered
    logical :: out_B    =.true.  ! Bacterial density (could be changed to generic source of disease, e.g., B, V,...)
    logical :: out_F    =.true.  ! Force of infection

    ! Clima
    logical :: out_rain =.true. ! Rainfall

    !----------------------------------------------------------
    integer :: disID                 ! Disease ID (0: Cholera, 1: Malaria)
    character(len=100) :: run_name   ! Name of output files
    character(len=100) :: pop_file   ! Name of population file
    character(len=100) :: rain_file  ! Name of rain/precipitation file
    !----------------------------------------------------------

    ! https://fortran-lang.org/en/learn/quickstart/arrays_strings/#array-of-strings
    character(len=100) ::  time_names(1)= [character(len=20) :: "time"]
    character(len=100) ::  lon_names(3) = [character(len=20) :: "lon", "longitude", "X"]
    character(len=100) ::  lat_names(3) = [character(len=20) :: "lat", "latitude", "Y"]
    character(len=100) ::  pop_names(3) = [character(len=20) :: "pop", "population", "population density"]
    character(len=100) ::  rain_names(5)= [character(len=20) :: "rain", "rainfall", "precipitation", "pt", "precip"]

    ! Attribute names
    character(len=100) ::  att_names(6) = [character(len=20) :: "standard_name", "long_name", "units", "calendar", "axis", "cell_methods"]
    
    character(len=100) :: lon_att(6)
    character(len=100) :: lat_att(6)
    character(len=100) :: time_att(6)
    character(len=100) :: rain_att(6)
    !----------------------------------------------------------



end MODULE mo_control