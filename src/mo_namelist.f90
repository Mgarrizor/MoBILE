MODULE mo_namelist
! This module deals with the NAMELIST(S) information

! Author: Miguel Garrido Zornoza (2024)
! Contact: mgarrizoraca@gmail.com
!

    use, intrinsic :: iso_fortran_env, only: stderr => error_unit
    use mo_const
    use mo_control


    use mo_constants !-- VECTRI


    implicit none

    CONTAINS

        subroutine namelist_inout(run_name,disID,nsteps,seed,spin_up)
            implicit none
            
            character(len=100), intent(out):: run_name
            integer, intent(out) :: disID, nsteps, seed, spin_up
            
            ! Local use only
            character(len=1000) :: line
            integer:: file_unit, iostats
            integer:: arg_num,ierr
            
            ! Define namelist
            namelist /INOUT/ run_name, disID, nsteps, seed, spin_up

            arg_num = 1
            ! Read first command line argument (namelist name)
            CALL GET_COMMAND_ARGUMENT(arg_num, VALUE=namelist_filename, STATUS=ierr)
            !
            ! Does the file exist?
            inquire (file=namelist_filename, iostat=iostats)

             if (iostats /= 0) then
                 write (stderr, '("Error: namelist file does not exist")')
                 return
             end if

            ! Open and read namelist
            open (action='read', file=namelist_filename, iostat=iostats, newunit=file_unit)
            read (nml=INOUT, iostat=iostats, unit=file_unit)

            ! If file exists but reading failed
            if (iostats /= 0) then
                write (stderr, '("Error: invalid namelist format")')
                ! Output line where failure occured
                ! https://degenerateconic.com/namelist-error-checking.html
                backspace(file_unit)
                read(file_unit,fmt='(A)') line
                write(stderr,'(A)') 'Invalid line in namelist is: '//trim(line)
                STOP
            end if
            
            close (file_unit)

        end subroutine namelist_inout

        subroutine namelist_human(pop_file,nagent,imm_file)
            implicit none

            character(len=100), intent(out):: pop_file, imm_file
            integer, intent(out) :: nagent

            ! Local use only
            character(len=1000) :: line
            integer:: file_unit, iostats

            ! Define namelist
            namelist /HUMAN/ pop_file, nagent, imm_file

            ! Does the file exist?
            inquire (file=namelist_filename, iostat=iostats)

             if (iostats /= 0) then
                 write (stderr, '("Error: namelist file does not exist")')
                 return
             end if

            ! Open and read namelist
            open (action='read', file=namelist_filename, iostat=iostats, newunit=file_unit)
            read (nml=HUMAN, iostat=iostats, unit=file_unit)

            ! If file exists but reading failed
            if (iostats /= 0) then
                write (stderr, '("Error: invalid namelist format")')
                ! Output line where failure occured
                ! https://degenerateconic.com/namelist-error-checking.html
                backspace(file_unit)
                read(file_unit,fmt='(A)') line
                write(stderr,'(A)') 'Invalid line in namelist is: '//trim(line)
            end if

            if (len(trim(imm_file)) /= 0) then
                print *, '--> Immunity forcing ', imm_file
                in_imm = .true.
            end if

            close (file_unit)

        end subroutine namelist_human



        subroutine namelist_clima(rain_file,t2m_file,area_file)
            implicit none

            character(len=100), intent(out):: rain_file, t2m_file, area_file
            
            ! Local use only
            character(len=1000) :: line
            integer:: file_unit, iostats
            
            ! Define namelist
            namelist /CLIMA/ rain_file, t2m_file, area_file

            ! Does the file exist?
            inquire (file=namelist_filename, iostat=iostats)

             if (iostats /= 0) then
                 write (stderr, '("Error: namelist file does not exist")')
                 return
             end if

            ! Open and read namelist
            open (action='read', file=namelist_filename, iostat=iostats, newunit=file_unit)
            read (nml=CLIMA, iostat=iostats, unit=file_unit)

            ! If file exists but reading failed
            if (iostats /= 0) then
                write (stderr, '("Error: invalid namelist format")')
                ! Output line where failure occured
                ! https://degenerateconic.com/namelist-error-checking.html
                backspace(file_unit)
                read(file_unit,fmt='(A)') line
                write(stderr,'(A)') 'Invalid line in namelist is: '//trim(line)
            end if

            if (len(trim(rain_file)) == 0) then
                print *, 'No rainfall input'
                out_rain = .false.
            end if 

            if (len(trim(t2m_file)) == 0) then
                print *, 'No temperature input'
                out_t2m = .false.
            end if

            if (len(trim(area_file)) == 0) then
                print *, 'No area input'
                if (agents) then 
                    STOP 
                end if
            end if

            
            close (file_unit)
            
        end subroutine namelist_clima


        subroutine namelist_const
        ! - Contains all model constants
        ! - Overwrites default values selected 
        !   by case at mo_const.f90

        ! - Especially usefull for sensitivity analysis and calibration 

        ! - You can use a NAMELIST to input values for specific parameters, and it is perfectly valid 
        !   to provide only a subset of the parameters defined in the NAMELIST. 
        !   When you input a single parameter value, the program will update only that specific parameter, 
        !   while the others will retain their default or previously assigned values.
            implicit none

            ! Local use only
            character(len=1000) :: line
            integer:: file_unit, iostats
            real :: growth_ratio ! nagent_max = ceiling(nagent*growth_ratio); 1.0 = no growth

            ! Define namelist
            ! - We should have here all model parameters that are being changed to their params.txt value
            !
            namelist /CONST/ mu_B, theta_e, theta_p, mu, birth_rate, rho, sigma, gamma, alpha, beta, & ! cholera disease params
                             mortality_file, birthrate_file, growth_ratio,                  & ! age/time-varying demographic rate files (blank = scalar mu/birth_rate) and population growth
                             m_long, m_short, D_grav, D_pop, H_0,                        & ! mobility params gravity model
                             B_0, fS_0, fI_0, fA_0, fR_0,                                & ! initial conditions
                             K_h, b_rate, P_v0, k_NB, P_h0, P_max,                       & ! Vector-human transmission params
                             wurbn_ratio,                                                & ! "Urban" fraction
                             wperm_ratio, wperm_default,                                 & ! Permanent fraction
                             wpond_min, wpond_max, wpond_ratio, wpond_shapep2,           & ! Pond scheme
                             rlarv_flushtau, rlarv_flushmin,                             & ! Rain-driven mortality
                             soilinfil_SA,                                               & ! Soil infiltration parameter for Sensitivity Analysis purposes
                             wpond_depthref, wpond_CN, wpond_ref,                        & ! Pond scheme (Asare et al. 2019?)
                             dgono,dsporo,                                               & !
                             e_0, e1, e2, A1, e_th, mat_rate, rho,                       & ! Immunity scheme
                             m_a, m_c, k_m, i_star_a, i_star_c, k_star,                  & ! Symptomatic scheme
                             d_c, d_a, k_e,                                          & ! 
                             alph_min,k_alph                                               !

            ! Does the file exist?
            inquire (file=namelist_filename, iostat=iostats)

             if (iostats /= 0) then
                 write (stderr, '("Error: namelist file does not exist")')
                 return
             end if

            growth_ratio = 1.0 ! Default: no population growth (nagent_max = nagent)

            ! Open and read namelist
            open (action='read', file=namelist_filename, iostat=iostats, newunit=file_unit)
            read (nml=CONST, iostat=iostats, unit=file_unit)

            
            ! If file exists but reading failed
            if (iostats /= 0) then
                write (stderr, '("Error: invalid namelist format")')
                ! Output line where failure occured
                ! https://degenerateconic.com/namelist-error-checking.html
                backspace(file_unit)
                read(file_unit,fmt='(A)') line
                write(stderr,'(A)') 'Invalid line in namelist is: '//trim(line)
            end if

            close (file_unit)

            ! Default birth_rate to mu if not set in params.txt (see const_disease's sentinel)
            if (birth_rate < 0.) then
                birth_rate = mu
            end if

            ! Materialize mu_age(:)/birth_years(:)/birth_vals(:): from the
            ! external files if given, else broadcast/collapse from the
            ! scalars above (reproduces today's constant-rate behavior).
            if (len(trim(mortality_file)) == 0) then
                mu_age(:) = mu
            else
                print *, '--> Age-specific mortality ', mortality_file
                call read_mortality_file(mortality_file, mu_age)
            end if

            if (len(trim(birthrate_file)) == 0) then
                allocate(birth_years(1), birth_vals(1))
                birth_years(1) = 0.
                birth_vals(1) = birth_rate
            else
                print *, '--> Time-varying birth rate ', birthrate_file
                call read_birthrate_file(birthrate_file, birth_years, birth_vals)
            end if

            ! growth_ratio < 1.0 (shrinkage) isn't supported by the additive
            ! extra-capacity mechanism in agents_init -- clamp instead of
            ! silently ignoring it.
            if (growth_ratio < 1.0) then
                print *, 'Warning: growth_ratio < 1.0 is not supported; clamping to 1.0'
                growth_ratio = 1.0
            end if
            nagent_max = ceiling(real(nagent) * growth_ratio)
        end subroutine namelist_const




















end MODULE mo_namelist