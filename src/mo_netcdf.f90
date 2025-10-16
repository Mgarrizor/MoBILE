MODULE mo_netcdf
! This module deals with the input and output
! of NetCDF files. From:
! https://docs.unidata.ucar.edu/netcdf-fortran/current/f90_The-NetCDF-Fortran-90-Interface-Guide.html
!
! Miguel Garrido Zornoza 2024 
! mgarrizoraca@gmail.com
!
    use netcdf
    use mo_control
    use mo_const

!----- VECTRI
#ifdef COUPLED
    ! Declarations or interfaces related to the coupled mode
    use mo_vectri
    !
#endif

    implicit none

    CONTAINS

      subroutine netcdf_input



      end subroutine netcdf_input

      subroutine netcdf_2D_output

        implicit none

        integer :: var_out=1, status

        var_out = 4
        ! 2D Fields
        if ((out_pop)) then
            !
            call write_check_2D(pop_dens,var_out,'NetCDF Status Population',ncid_grp(2))
            !
        end if 

        if ((out_Q)) then            
            !
            !call write_check_2D(Q(xy_seed,:),var_out,'NetCDF Status Q')
            !

            status = nf90_put_var(ncid = ncid_out, varid = VarId(var_out), & 
                                  values = reshape((Q(xy_seed,:)), shape = (/ nlon, nlat /)))
            var_out = var_out + 1

        end if 

        if ((out_D)) then            
           
            status = nf90_put_var(ncid = ncid_out, varid = VarId(var_out), & 
                                 values = reshape((dist(xy_seed,:)), shape = (/ nlon, nlat /)))
            var_out = var_out + 1
        end if 

        if ((out_age)) then            
            
            status = nf90_put_var(ncid = ncid_grp(2), varid = VarId(var_out), & 
                                 values = age_counts(:))
            var_out = var_out + 1
        end if 


#ifdef COUPLED
        ! Declarations or interfaces related to the coupled mode
        !
        if ((out_wurbn)) then
            !
            status = nf90_put_var(ncid = ncid_grp(4), varid = VarId(var_out), & 
                                 values = reshape((rwaterurbn*wurbn_ratio), shape = (/ nlon, nlat /)))
            var_out = var_out + 1!
        end if 
        !
        if ((out_wperm)) then
            !
            status = nf90_put_var(ncid = ncid_grp(4), varid = VarId(var_out), & 
                                 values = reshape((rwaterperm*wperm_ratio), shape = (/ nlon, nlat /)))
            var_out = var_out + 1!
        end if 
        !
#endif
        

        status = nf90_close(ncid_out)

      end subroutine netcdf_2D_output

      subroutine write_check_2D(var,var_out,err_mes,ncID)
      ! Put variable into NetCDf file and check for the status
      ! If error then stop simulation.
      !
      implicit none 
      !
      real, intent(in) :: var(nlon,nlat)
      integer, intent(inout):: var_out
      character(len=*) :: err_mes
      integer, intent(in) :: ncID

      ! Local use only
      integer :: status

      status = nf90_put_var(ncid = ncID, varid = VarId(var_out), & 
                            values = reshape((var), shape = (/ nlon, nlat /)))
      var_out = var_out + 1
      if(status /= nf90_noerr) then
        print *, err_mes
        STOP
      end if

      end subroutine

      subroutine netcdf_3D_output(itime,Var3D)
        implicit none
        integer, intent(in) :: itime, Var3D

        ! Local use
        integer :: var_out  !,status
        integer :: k

        ! 3D Fields
        var_out = Var3D
      
        if ((out_S)) then 
          !
          call write_check_3D(itime,S,var_out,'NetCDF Status S',ncid_grp(2))
          !
        end if 

        if ((out_I) .and. (out_Ia)) then
            !
            call write_check_3D(itime,I,var_out,'NetCDF Status I',ncid_sbgrp(3))
            !
        else if (out_I) then
            !
            call write_check_3D(itime,I,var_out,'NetCDF Status I',ncid_grp(2))
            !
        end if

        if (out_Ia) then
            !
            do k = 1, size(age_blocks(:))
                call write_check_3D(itime,Ia(:,k),var_out,'NetCDF Status Ia',ncid_sbgrp(3))
            end do
            !
        end if

        if ((out_A) .and. (out_Aa)) then
            !
            call write_check_3D(itime,A,var_out,'NetCDF Status A',ncid_sbgrp(4))
            !
        else if (out_A) then
            !
            call write_check_3D(itime,A,var_out,'NetCDF Status A',ncid_grp(2))
            !
        end if

        if (out_Aa) then
            !
            do k = 1, size(age_blocks(:))
                call write_check_3D(itime,Aa(:,k),var_out,'NetCDF Status Aa',ncid_sbgrp(4))
            end do
            !
        end if

        if ((out_R)) then
            !
            call write_check_3D(itime,R,var_out,'NetCDF Status R',ncid_grp(2))
            !
        end if

        if ((out_B)) then
            !
            call write_check_3D(itime,B,var_out,'NetCDF Status B',ncid_out)
            !
        end if

        if ((out_F)) then
            !
            call write_check_3D(itime,F,var_out,'NetCDF Status F',ncid_out)
            !
        end if

        ! ============================== Climate ======================================

        if ((out_rain)) then
            !
            !call write_check_3D(itime,rainfall(:,itime),var_out,'NetCDF Status Rainfall')
            call write_check_3D(itime,rainfall(:,itime),var_out,'NetCDF Status Rainfall',ncid_grp(3))
            !
        end if 

        if ((out_t2m)) then
            !
            !call write_check_3D(itime,t2m(:,itime),var_out,'NetCDF Status Temperature')
            call write_check_3D(itime,t2m(:,itime),var_out,'NetCDF Status Temperature',ncid_grp(3))
            !
        end if 

        ! ============================== VECTRI ======================================
#ifdef COUPLED
        if ((out_vect)) then
            !
            call write_check_3D(itime,zvect_density,var_out,'NetCDF Status Vector density',ncid_grp(1))
            !
        end if
        !
        if ((out_vecinfc)) then
            !
            call write_check_3D(itime,zvecinfc*zvect_density,var_out,'NetCDF Status Infective Vector density',ncid_grp(1))
            !
        end if
        !
        !
        if ((out_larv)) then
            !
            call write_check_3D(itime,sum(rlarv(:,:), dim = 1),var_out,'NetCDF Status Larval density',ncid_grp(1))
            !
        end if
        !
        if ((out_wpond)) then
            !
            call write_check_3D(itime,rwaterpond*wpond_ratio,var_out,'NetCDF Status waterpond',ncid_grp(4))
            !
        end if
        !
        if ((out_EIR)) then
            !
            call write_check_3D(itime,EIR,var_out,'NetCDF Status Entomological Inoculation Rate',ncid_grp(2))
            !
        end if
        !
        if ((out_E)) then
            !
            call write_check_3D(itime,E,var_out,'NetCDF Status E',ncid_grp(2))
            !
        end if
        !
        if ((out_imm)) then
            !
            call write_check_3D(itime,imm,var_out,'NetCDF Status Endemicity level / Immunity',ncid_grp(2))
            !
        end if
        !
#endif


      end subroutine netcdf_3D_output

      subroutine write_check_3D(itime,var,var_out,err_mes, ncID)
      ! Put variable into NetCDf file and check for the status
      ! If error then stop simulation.
      !
      implicit none 
      !
      real, intent(in) :: var(nlon,nlat)
      integer, intent(in) :: itime
      integer, intent(inout):: var_out
      character(len=*) :: err_mes
      integer, intent(in) :: ncID 

      ! Local use only
      integer :: status

      status = nf90_put_var(ncid = ncID, varid = VarId(var_out), & 
                            values = reshape((var), shape = (/ nlon, nlat /)), &
                            start = (/ 1, 1, itime /))
      var_out = var_out + 1

      if(status /= nf90_noerr) then
       print *, err_mes
       print *, itime
       STOP
      end if

      end subroutine write_check_3D


      !subroutine read_slice(itime)
        ! Test subroutine for better performance (read drivers each time-step)
      !  implicit none 

      !  integer, intent(in) :: itime

        !integer :: status

      !  print*, "You're using a subroutine that does nothing!"

      !  status = nf90_get_var(ncTempID, TempVarID, point_t2m, start=(/1,1,itime/),count=(/nlon,nlat,1/))
      !  status = nf90_get_var(ncRainID, RainVarID, rain_2d, start=(/1,1,itime/),count=(/nlon,nlat,1/))

      !  point_rain = reshape(rain_2d, (/nxy/))

      !end subroutine read_slice

      subroutine netcdf_init(nlon,nlat,nsteps,lon_coord,lat_coord,Var3D)
        implicit none

    ! Layout *******************************
    !
    !   nf90_create        ! create netCDF dataset: enter define mode
    !           ...
    !   nf90_def_dim       ! define dimensions: from name and length
    !           ...
    !   nf90_def_var       ! define variables: from name, type, dims
    !           ...
    !   nf90_put_att       ! assign attribute values
    !           ...
    !   nf90_enddef        ! end definitions: leave define mode
    !           ...
    !   nf90_put_var       ! provide values for variable
    !           ... 
    !   nf90_close 

    ! " Only one call is needed to create a netCDF dataset, 
      ! at which point you will be in the first of two netCDF modes. 
      ! When accessing an open netCDF dataset, it is either in 
      ! define mode or data mode. In define mode, you can create dimensions, 
      ! variables, and new attributes, but you cannot read or write variable data. 
      ! In data mode, you can access data and change existing attributes, but you 
      ! are not permitted to create new dimensions, variables, or attributes."
 
        integer, intent(in) :: nlat, nlon, nsteps
        real, allocatable, intent(in) :: lat_coord(:)
        real, allocatable, intent(in) :: lon_coord(:) 
        integer, intent(out) :: Var3D

        integer :: status, indx, k
        integer :: var_out=1, dim


        ! Horrible, clean it up!
        ! Lon+Lat+Time+ Rest
        dim = 3 + merge(1, 0, out_pop)+merge(1, 0, out_S)  &
                                      +merge(1, 0, out_I)+merge(1, 0, out_R) &
                                      +merge(1, 0, out_B)+merge(1, 0, out_F) &
                                      +merge(1, 0, out_A)+merge(1, 0, out_Q) &
                                      +merge(1, 0, out_D)+merge(1, 0, out_rain) &
                                      +merge(1, 0, out_t2m) &
                                      +merge(1, 0, out_age)

        if (out_Ia) then
            dim = dim + size(age_blocks(:))
        end if
        if (out_Aa) then
            dim = dim + size(age_blocks(:))
        end if
                                      

#ifdef COUPLED
        ! Declarations or interfaces related to the coupled mode
        dim = dim +merge(1, 0, out_wurbn) +merge(1, 0, out_wperm)   +merge(1, 0, out_wpond) &
                  +merge(1, 0, out_vect)  +merge(1, 0, out_vecinfc) +merge(1, 0, out_larv)&
                  +merge(1, 0, out_EIR)   +merge(1, 0, out_E)       +merge(1, 0, out_imm)
        !
#endif

        allocate(VarId(dim))


        !=== Create 
        ! - Returns a netCDF ID that can subsequently be used 
        !   to refer to the netCDF dataset in other netCDF function calls
        ! - Create new dataset and assign main spatial dimensions
        status = nf90_create(path=trim(run_name)//".nc", cmode = NF90_NETCDF4, ncid = ncid_out)
        
        status = nf90_def_dim(ncid = ncid_out, name = "lon", len = nlon,   dimid = DimId(1))
        status = nf90_def_dim(ncid = ncid_out, name = "lat", len = nlat,   dimid = DimId(2))
        status = nf90_def_dim(ncid = ncid_out, name = "time",len = nsteps, dimid = DimId(3))
        
        status = nf90_def_dim(ncid = ncid_out, name = "age",len = size(age_weights), dimid = DimId(4))
        
        ! See below "About coordinate systems"

        ! ------------- Longitude --------------------------------
        VarId(var_out)=var_out
        status = nf90_def_var(ncid = ncid_out, name = "lon", xtype = nf90_double, &
                      dimids = DimId(1), varid = VarId(var_out))
        ! Write longitude attributes
        do indx=1,size(att_names)
            if (len(trim(lon_att(indx))) /= 0) then 
              status = nf90_put_att(ncid=ncid_out, varid = VarId(var_out), name=att_names(indx), values=lon_att(indx))
            end if 
        end do
        var_out = var_out + 1

        ! ------------- Latitude --------------------------------
        VarId(var_out)=var_out
        status = nf90_def_var(ncid = ncid_out, name = "lat", xtype = nf90_double, &
                      dimids = DimId(2), varid = VarId(var_out))
        ! Write latitude attributes
        do indx=1,size(att_names)
            if (len(trim(lat_att(indx))) /= 0) then 
              status = nf90_put_att(ncid=ncid_out, varid = VarId(var_out), name=att_names(indx), values=lat_att(indx))
            end if 
        end do
        var_out = var_out + 1

        ! ------------- Time --------------------------------
        VarId(var_out)=var_out
        status = nf90_def_var(ncid = ncid_out, name = "time", xtype = nf90_double, &
                      dimids = DimId(3), varid = VarId(var_out))

        if (out_rain) then
        ! Write time attributes
          do indx=1,size(att_names)
                !
                if (len(trim(time_att(indx))) /= 0) then 
                  status = nf90_put_att(ncid=ncid_out, varid = VarId(var_out), name=att_names(indx), values=time_att(indx))
                end if 
                !
          end do
        end if
        var_out = var_out + 1
        !

        !
        ! We write time attributes in the 3D field along the climatic forcings

        
        ! Define variables and assign attributes and values
        ! Constrain: order should be the same of def_var!
        ! 2D Fields (x,y) (no time) --------------------------------------------
        !
        !
        status = nf90_def_grp(parent_ncid = ncid_out, name = 'Human', new_ncid = ncid_grp(2))
        if(status /= nf90_noerr) then
          print *, 'NetCDF Status: error creating group <<Human>> ; status =', status
          STOP
        end if
        !
        if ((out_pop)) then

            VarId(var_out)=var_out
            status = nf90_def_var(ncid = ncid_grp(2), name = "pop", xtype = nf90_double, &
                      dimids = (/ DimId(1), DimId(2) /), varid = VarId(var_out))
            status = nf90_put_att(ncid = ncid_grp(2), varid = VarId(var_out), name = "units", values = "km^-2")
         !   status = nf90_put_att(ncid = ncid_out, varid = VarId(var_out), name = "_FillValue", values = FillValue)
            status = nf90_def_var_fill(ncid_grp(2), VarId(var_out), 0, FillValue)
            var_out = var_out + 1

        end if

        if ((out_Q)) then

            VarId(var_out)=var_out
            status = nf90_def_var(ncid = ncid_out, name = "Q", xtype = nf90_double, &
                      dimids = (/ DimId(1), DimId(2) /), varid = VarId(var_out))
            status = nf90_put_att(ncid = ncid_out, varid = VarId(var_out), name = "units", values = "[]")
            var_out = var_out + 1

        end if

        if ((out_D)) then

            VarId(var_out)=var_out
            status = nf90_def_var(ncid = ncid_out, name = "D", xtype = nf90_double, &
                      dimids = (/ DimId(1), DimId(2) /), varid = VarId(var_out))
            status = nf90_put_att(ncid = ncid_out, varid = VarId(var_out), name = "units", values = "[km]")
            var_out = var_out + 1

        end if

        if ((out_age)) then

            VarId(var_out)=var_out
            status = nf90_def_var(ncid = ncid_grp(2), name = "Age", xtype = nf90_double, &
                     dimids = DimId(4), varid = VarId(var_out))
            status = nf90_put_att(ncid = ncid_grp(2), varid = VarId(var_out), name = "units", values = "[counts]")
            var_out = var_out + 1

        end if


#ifdef COUPLED
        !
        status = nf90_def_grp(parent_ncid = ncid_out, name = 'Hydro', new_ncid = ncid_grp(4))
        if(status /= nf90_noerr) then
          print *, 'NetCDF Status: error creating group <<Hydro>> ; status =', status
          STOP
        end if
        !
        ! Declarations or interfaces related to the coupled mode
        if ((out_wurbn)) then
            !
            VarId(var_out)=var_out
            status = nf90_def_var(ncid = ncid_grp(4), name = "wurbn", xtype = nf90_double, &
                      dimids = (/ DimId(1), DimId(2) /), varid = VarId(var_out))
            status = nf90_put_att(ncid = ncid_grp(4), varid = VarId(var_out), name = "units", values = "[fraction]")
            var_out = var_out + 1
            !
        end if
        !
        if ((out_wperm)) then
            !
            VarId(var_out)=var_out
            status = nf90_def_var(ncid = ncid_grp(4), name = "wperm", xtype = nf90_double, &
                      dimids = (/ DimId(1), DimId(2) /), varid = VarId(var_out))
            status = nf90_put_att(ncid = ncid_grp(4), varid = VarId(var_out), name = "units", values = "[fraction]")
            var_out = var_out + 1
            !
        end if
        !
#endif
        

        ! 3D Fields (x,y,t)
        !
        if ((out_Ia)) then
            status = nf90_def_grp(parent_ncid = ncid_out, name = 'I', new_ncid = ncid_sbgrp(3))
            if(status /= nf90_noerr) then
              print *, 'NetCDF Status: error creating subgroup <<I>> ; status =', status
              STOP
            end if
        end if
        !
        !
        if ((out_Aa)) then
            status = nf90_def_grp(parent_ncid = ncid_out, name = 'A', new_ncid = ncid_sbgrp(4))
            if(status /= nf90_noerr) then
              print *, 'NetCDF Status: error creating subgroup <<A>> ; status =', status
              STOP
            end if
        end if
        !
        !==================
        Var3D = var_out

        ! ============================== Disease ======================================
        if ((out_S)) then

            VarId(var_out)=var_out
            status = nf90_def_var(ncid = ncid_grp(2), name = "S", xtype = nf90_double, &
                      dimids = (/ DimId(1), DimId(2), DimId(3)/), varid = VarId(var_out))
            status = nf90_put_att(ncid = ncid_grp(2), varid = VarId(var_out), name = "units", values = "km^-2")
            status = nf90_put_att(ncid = ncid_grp(2), varid = VarId(var_out), name = "long_name", values = "Susceptible population density")
            var_out = var_out + 1

        end if

        if ((out_I) .and. (out_Ia)) then

            VarId(var_out)=var_out
            status = nf90_def_var(ncid = ncid_sbgrp(3), name = "I_bulk", xtype = nf90_double, &
                      dimids = (/ DimId(1), DimId(2), DimId(3)/), varid = VarId(var_out))
            status = nf90_put_att(ncid = ncid_sbgrp(3), varid = VarId(var_out), name = "units", values = "km^-2")
            status = nf90_put_att(ncid = ncid_sbgrp(3), varid = VarId(var_out), name = "long_name", values = "Infected symptomatic population density")
            var_out = var_out + 1

        else if (out_I) then

            VarId(var_out)=var_out
            status = nf90_def_var(ncid = ncid_grp(2), name = "I", xtype = nf90_double, &
                      dimids = (/ DimId(1), DimId(2), DimId(3)/), varid = VarId(var_out))
            status = nf90_put_att(ncid = ncid_grp(2), varid = VarId(var_out), name = "units", values = "km^-2")
            status = nf90_put_att(ncid = ncid_grp(2), varid = VarId(var_out), name = "long_name", values = "Infected symptomatic population density")
            var_out = var_out + 1

        end if

        if ((out_Ia)) then
            do k = 1, size(age_blocks(:))
                VarId(var_out)=var_out
                status = nf90_def_var(ncid = ncid_sbgrp(3), name = I_age_names(k), xtype = nf90_double, &
                          dimids = (/ DimId(1), DimId(2), DimId(3)/), varid = VarId(var_out))
                status = nf90_put_att(ncid = ncid_sbgrp(3), varid = VarId(var_out), name = "units", values = "km^-2")
                status = nf90_put_att(ncid = ncid_sbgrp(3), varid = VarId(var_out), name = "long_name", values = "Age-disaggregated Infected symptomatic population density")
                var_out = var_out + 1
            end do
        end if

        if ((out_A) .and. (out_Aa)) then

            VarId(var_out)=var_out
            status = nf90_def_var(ncid = ncid_sbgrp(4), name = "A_bulk", xtype = nf90_double, &
                      dimids = (/ DimId(1), DimId(2), DimId(3)/), varid = VarId(var_out))
            status = nf90_put_att(ncid = ncid_sbgrp(4), varid = VarId(var_out), name = "units", values = "km^-2")
            status = nf90_put_att(ncid = ncid_sbgrp(4), varid = VarId(var_out), name = "long_name", values = "Infected asymptomatic population density")
            var_out = var_out + 1

        else if (out_A) then

            VarId(var_out)=var_out
            status = nf90_def_var(ncid = ncid_grp(2), name = "A", xtype = nf90_double, &
                      dimids = (/ DimId(1), DimId(2), DimId(3)/), varid = VarId(var_out))
            status = nf90_put_att(ncid = ncid_grp(2), varid = VarId(var_out), name = "units", values = "km^-2")
            status = nf90_put_att(ncid = ncid_grp(2), varid = VarId(var_out), name = "long_name", values = "Infected asymptomatic population density")
            var_out = var_out + 1

        end if

        if ((out_Aa)) then
            do k = 1, size(age_blocks(:))
                VarId(var_out)=var_out
                status = nf90_def_var(ncid = ncid_sbgrp(4), name = A_age_names(k), xtype = nf90_double, &
                          dimids = (/ DimId(1), DimId(2), DimId(3)/), varid = VarId(var_out))
                status = nf90_put_att(ncid = ncid_sbgrp(4), varid = VarId(var_out), name = "units", values = "km^-2")
                status = nf90_put_att(ncid = ncid_sbgrp(4), varid = VarId(var_out), name = "long_name", values = "Age-disaggregated Infected symptomatic population density")
                var_out = var_out + 1
            end do
        end if

        if ((out_R)) then

            VarId(var_out)=var_out
            status = nf90_def_var(ncid = ncid_grp(2), name = "R", xtype = nf90_double, &
                      dimids = (/ DimId(1), DimId(2), DimId(3)/), varid = VarId(var_out))
            status = nf90_put_att(ncid = ncid_grp(2), varid = VarId(var_out), name = "units", values = "km^-2")
            status = nf90_put_att(ncid = ncid_grp(2), varid = VarId(var_out), name = "long_name", values = "Recovered population density")
            var_out = var_out + 1

        end if
!!
        if ((out_B)) then

            VarId(var_out)=var_out
            status = nf90_def_var(ncid = ncid_out, name = "B", xtype = nf90_double, &
                      dimids = (/ DimId(1), DimId(2), DimId(3)/), varid = VarId(var_out))
            status = nf90_put_att(ncid = ncid_out, varid = VarId(var_out), name = "units", values = "Dimensionless")
            status = nf90_put_att(ncid = ncid_out, varid = VarId(var_out), name = "long_name", values = "Bacterial load")
            var_out = var_out + 1

        end if
!!
        if ((out_F)) then

            VarId(var_out)=var_out
            status = nf90_def_var(ncid = ncid_out, name = "F", xtype = nf90_double, &
                      dimids = (/ DimId(1), DimId(2), DimId(3)/), varid = VarId(var_out))
            status = nf90_put_att(ncid = ncid_out, varid = VarId(var_out), name = "units", values = "day^-1")
            status = nf90_put_att(ncid = ncid_out, varid = VarId(var_out), name = "long_name", values = "Force of infection")
            var_out = var_out + 1

        end if

        ! ============================== Climate ======================================

        !
        status = nf90_def_grp(parent_ncid = ncid_out, name = 'Climate', new_ncid = ncid_grp(3))
        if(status /= nf90_noerr) then
          print *, 'NetCDF Status: error creating group <<Climate>> ; status =', status
          STOP
        end if
        !
        if ((out_rain)) then


          VarId(var_out)=var_out
          status = nf90_def_var(ncid = ncid_grp(3), name = "rain", xtype = nf90_double, &
                    dimids = (/ DimId(1), DimId(2) , DimId(3) /), varid = VarId(var_out))

          status = nf90_def_var_fill(ncid_grp(3), VarId(var_out), 0, FillValue_rain)
      
          ! Write rainfall attributes
          do indx=1,size(att_names)
              !
              if (len(trim(rain_att(indx))) /= 0) then 
                !
                status = nf90_put_att(ncid=ncid_grp(3), varid = VarId(var_out), name=att_names(indx), values=rain_att(indx))
              end if
              !
          end do
            !
          var_out = var_out + 1
        end if

        if ((out_t2m)) then


          VarId(var_out)=var_out
          status = nf90_def_var(ncid = ncid_grp(3), name = "t2m", xtype = nf90_double, &
                    dimids = (/ DimId(1), DimId(2) , DimId(3) /), varid = VarId(var_out))
          
          status = nf90_def_var_fill(ncid_grp(3), VarId(var_out), 0, FillValue_temp)
          
          ! Write temperature attributes
          do indx=1,size(att_names)
              !
              if (len(trim(temp_att(indx))) /= 0) then 
                !
                status = nf90_put_att(ncid=ncid_grp(3), varid = VarId(var_out), name=att_names(indx), values=temp_att(indx))
              end if
              !
          end do
            !
          var_out = var_out + 1
        end if


        ! ============= VECTRI ==================

#ifdef COUPLED
        !
        ! If VECTRI then define 'Vector' group
        !
        status = nf90_def_grp(parent_ncid = ncid_out, name = 'Vector', new_ncid = ncid_grp(1))
        if(status /= nf90_noerr) then
          print *, 'NetCDF Status: error creating group <<Vector>> ; status =', status
          STOP
        end if
        !
        if (out_vect) then
          !
          VarId(var_out)=var_out
          status = nf90_def_var(ncid = ncid_grp(1), name = "V", xtype = nf90_double, &
                    dimids = (/ DimId(1), DimId(2), DimId(3)/), varid = VarId(var_out))
          status = nf90_put_att(ncid = ncid_grp(1), varid = VarId(var_out), name = "units", values = "m^-2")
          status = nf90_put_att(ncid = ncid_grp(1), varid = VarId(var_out), name = "long_name", values = "Vector density")
          var_out = var_out + 1
          !
        end if
        !
        if (out_vecinfc) then
          !
          VarId(var_out)=var_out
          status = nf90_def_var(ncid = ncid_grp(1), name = "Vinf", xtype = nf90_double, &
                    dimids = (/ DimId(1), DimId(2), DimId(3)/), varid = VarId(var_out))
          status = nf90_put_att(ncid = ncid_grp(1), varid = VarId(var_out), name = "units", values = "m^-2")
          status = nf90_put_att(ncid = ncid_grp(1), varid = VarId(var_out), name = "long_name", values = "Infective vector density")
          var_out = var_out + 1
          !
        end if
        !
        if (out_larv) then
          !
          VarId(var_out)=var_out
          status = nf90_def_var(ncid = ncid_grp(1), name = "L", xtype = nf90_double, &
                    dimids = (/ DimId(1), DimId(2), DimId(3)/), varid = VarId(var_out))
          status = nf90_put_att(ncid = ncid_grp(1), varid = VarId(var_out), name = "units", values = "m^-2")
          status = nf90_put_att(ncid = ncid_grp(1), varid = VarId(var_out), name = "long_name", values = "Larval density")
          var_out = var_out + 1
          !
        end if
        !
        if (out_wpond) then
          !
          VarId(var_out)=var_out
          status = nf90_def_var(ncid = ncid_grp(4), name = "wpond", xtype = nf90_double, &
                    dimids = (/ DimId(1), DimId(2), DimId(3)/), varid = VarId(var_out))
          status = nf90_put_att(ncid = ncid_grp(4), varid = VarId(var_out), name = "units", values = "[fraction]")
          status = nf90_put_att(ncid = ncid_grp(4), varid = VarId(var_out), name = "long_name", values = "Fraction of temporary rain-driven ponds")
          var_out = var_out + 1
          !
        end if
        !
        if (out_EIR) then
          !
          VarId(var_out)=var_out
          status = nf90_def_var(ncid = ncid_grp(2), name = "EIR", xtype = nf90_double, &
                    dimids = (/ DimId(1), DimId(2), DimId(3)/), varid = VarId(var_out))
          status = nf90_put_att(ncid = ncid_grp(2), varid = VarId(var_out), name = "units", values = "day^-1")
          status = nf90_put_att(ncid = ncid_grp(2), varid = VarId(var_out), name = "long_name", values = "Entomological Inoculation Rate")
          var_out = var_out + 1
          !
        end if
        !
        if ((out_E)) then

            VarId(var_out)=var_out
            status = nf90_def_var(ncid = ncid_grp(2), name = "E", xtype = nf90_double, &
                      dimids = (/ DimId(1), DimId(2), DimId(3)/), varid = VarId(var_out))
            status = nf90_put_att(ncid = ncid_grp(2), varid = VarId(var_out), name = "units", values = "km^-2")
            status = nf90_put_att(ncid = ncid_grp(2), varid = VarId(var_out), name = "long_name", values = "Exposed population density")
            var_out = var_out + 1

        end if
        !
        if (out_imm) then
          !
          VarId(var_out)=var_out
          status = nf90_def_var(ncid = ncid_grp(2), name = "e_l", xtype = nf90_double, &
                    dimids = (/ DimId(1), DimId(2), DimId(3)/), varid = VarId(var_out))
          status = nf90_put_att(ncid = ncid_grp(2), varid = VarId(var_out), name = "units", values = "adimensional")
          status = nf90_put_att(ncid = ncid_grp(2), varid = VarId(var_out), name = "long_name", values = "Endemicity level / Immunity")
          var_out = var_out + 1
          !
        end if
        !
#endif

        ! Define groups
        



        ! Leave define mode to write variable values

        status = nf90_enddef(ncid = ncid_out)

        ! About coordinate systems
        !        - https://docs.unidata.ucar.edu/nug/current/best_practices.html#bp_Coordinate-Systems

        ! "A coordinate variable is a one-dimensional variable with the same name as a dimension, 
        ! which names the coordinate values of the dimension. It must not have any missing data 
        ! (for example, no _FillValue or missing_value attributes) and must be strictly monotonic 
        ! (values increasing or decreasing).
        !
        ! / Make coordinate variables for every dimension possible 
        !   (except for string length dimensions).
        ! / Give each coordinate variable at least unit and long_name attributes 
        !   to document its meaning.
        ! / Use an existing netCDF Convention for your coordinate variables, especially 
        !   to identify spatio-temporal coordinates.
        ! / Use shared dimensions to indicate that two variables use the same coordinates 
        !   along that dimension. If two variables' dimensions are not related, create 
        !   separate dimensions for them, even if they happen to have the same length."
        !
        ! Conventions
        ! How to create a coordinate system: 
        !        - https://www.bic.mni.mcgill.ca/users/sean/Docs/netcdf/guide.txn_15.html
        ! General info:
        !        - https://docs.unidata.ucar.edu/nug/current/best_practices.html#Conventions
        !        - https://www.unidata.ucar.edu/software/netcdf/conventions.html

        ! Lon/lat
        
        status = nf90_put_var(ncid = ncid_out, varid = VarId(1), values = lon_coord)
        status = nf90_put_var(ncid = ncid_out, varid = VarId(2), values = lat_coord)

        ! Time
        if (out_rain) then
          status = nf90_put_var(ncid = ncid_out, varid = VarId(3), values = time_coord(1:nsteps))
        end if
        
      end subroutine netcdf_init

      subroutine netcdf_read_grid(pop_file,grid,nlon,nlat,nxy,pop_dens,lon_coord,lat_coord,mask_pop,nsteps)
      ! Read input files on humans and get frid characteristics following
      ! https://docs.unidata.ucar.edu/netcdf-fortran/current/f90-use-of-the-netcdf-library.html#f90-reading-a-netcdf-dataset-with-known-names
      !
      ! Layout --------------------------------------------------------
      !      nf90_open            ! open existing netCDF dataset
      !        ...
      !      nf90_inq_dimid       ! get dimension IDs
      !        ...
      !      nf90_inq_varid       ! get variable IDs
      !        ...
      !      nf90_get_att         ! get attribute values
      !        ...
      !      nf90_get_var         ! get values of variables
      !        ...
      !      nf90_close           ! close netcdf dataset
      !----------------------------------------------------------------
        implicit none
        character(len=100), intent(in):: pop_file
       ! character(len=100) :: long_lat
        integer, intent(out) :: nlon, nlat, nxy
        real, allocatable, intent(out) :: pop_dens(:)
        real, allocatable, intent(out) :: lon_coord(:)
        real, allocatable, intent(out) :: lat_coord(:)
        real, allocatable, intent(out) :: grid(:,:)
        logical, allocatable, intent(out) :: mask_pop(:)
        integer, intent(out) :: nsteps

        ! Rainfall definitions --------------------------
        !character(len=100), intent(in) :: rain_file
        !real, allocatable, intent(out) :: rainfall(:,:)

        ! Local use only 
        integer :: TimeVarID, TimeDimID
        ! -----------------------------------

        ! Local use only
        integer :: status, LatDimID, LonDimID, LatVarID, LonVarID, PopVarID
        integer :: numdims, indx_lat=1, indx_lon=1, indx    !indx_pop, indx_rain



        FillValue = nf90_fill_double

        ! Open file
        status = nf90_open(path = pop_file, mode = nf90_nowrite, ncid = ncid_in)

        ! Inquire dimensions and get their IDs ----------------------------------------
        do indx=1,size(lat_names)
          status = nf90_inq_dimid(ncid=ncid_in, name=lat_names(indx), dimid=LatDimID)

          if (status == nf90_noerr) then
            indx_lat = indx
            !print *, 'NetCDF Status: found latitude dimension named --> ', lat_names(indx_lat)
            exit
          elseif((indx == size(lat_names)) .and. (status /= nf90_noerr)) then
            print *, 'NetCDF Status: latitude dimension not indentified'
            STOP
          end if
        end do

        do indx=1,size(lon_names)
          status = nf90_inq_dimid(ncid=ncid_in, name=lon_names(indx), dimid=LonDimID)

          if (status == nf90_noerr) then
            indx_lon = indx
           !print *, 'NetCDF Status: found longitude dimension named --> ', lon_names(indx_lon)
            exit
          elseif((indx == size(lon_names)) .and. (status /= nf90_noerr)) then
            print *, 'NetCDF Status: longitude dimension not indentified'
            STOP
          end if
        end do

        ! Now get the name (optional) and the length out
        status = nf90_inquire_dimension(ncid=ncid_in, dimid=LatDimID, len=nlat)
        status = nf90_inquire_dimension(ncid=ncid_in, dimid=LonDimID, len=nlon)

        ! Error handling here for inquired dimensions -----------

        !--------------------------------------------------------
        ! Allocate arrays based on the inquired Lon, Lat dimensions 
        allocate(lat_coord(nlat))
        allocate(lon_coord(nlon))
        nxy = nlat*nlon
        print *, '------------------------'
        print '("Grid -- lon:",i6," lat:" ,i6," nxy: " ,i10," ")', nlon, nlat, nxy
        allocate(pop_dens(nxy))
        allocate(mask_pop(nxy))
        allocate(D(nxy))
        allocate(grid(nlon,nlat))

        ! Inquire variable IDs
        status = nf90_inq_varid(ncid=ncid_in, name=lat_names(indx_lat), varid=LatVarID)
        status = nf90_inq_varid(ncid=ncid_in, name=lon_names(indx_lon), varid=LonVarID)

        ! Get population ID
        !
        do indx=1,size(pop_names)
          status = nf90_inq_varid(ncid=ncid_in, name=pop_names(indx), varid=PopVarID)

          if (status == nf90_noerr) then
            exit
          elseif((indx == size(pop_names)) .and. (status /= nf90_noerr)) then
            print *, 'NetCDF Status: populaton variable not indentified'
            STOP
          end if
        end do

        ! Get information of variables from their IDs (numdims) - not in use since we expect a fixed dimensionality
        status = nf90_inquire_variable(ncid=ncid_in, varid=LatVarID, ndims = numdims)
        status = nf90_inquire_variable(ncid=ncid_in, varid=LonVarID, ndims = numdims)
        status = nf90_inquire_variable(ncid=ncid_in, varid=PopVarID, ndims = numdims)

        ! Get attributes
        do indx=1,size(att_names)
            status = nf90_get_att(ncid=ncid_in, varid=LonVarID, name=att_names(indx), values=lon_att(indx))
            status = nf90_get_att(ncid=ncid_in, varid=LatVarID, name=att_names(indx), values=lat_att(indx))
        end do

        status = nf90_get_att(ncid=ncid_in, varid=PopVarID, name="_FillValue", values=FillValue) 

        ! Get variable values
        status = nf90_get_var(ncid=ncid_in, varid=LatVarID, values=lat_coord)
        status = nf90_get_var(ncid=ncid_in, varid=LonVarID, values=lon_coord)

        ! Get variables and set them to a standard missing value where = to attribute _FillValue
        ! https://docs.unidata.ucar.edu/netcdf-fortran/current/f90-variables.html#f90-fill-values
        status = nf90_get_var(ncid=ncid_in, varid=PopVarID, values=grid)

        pop_dens = reshape(grid, (/nxy/))

        where(pop_dens == FillValue) mask_pop = .false.
        where(pop_dens < eps) pop_dens = 0.

        where(pop_dens < eps) mask_pop = .false.
        where(pop_dens > eps) mask_pop = .true.

        where(pop_dens > eps) D = 1/log(pop_dens+1)

        

        if (out_rain) then

              ! We need to extract the dates of the forcing and its total length, ntime, so that
              ! nsteps <= ntime.

              ! Open file
              status = nf90_open(path = rain_file, mode = nf90_nowrite, ncid = ncRainID)

              ! Inquire about time and get its DimID 
              !
              do indx=1,size(time_names)
                !
                status = nf90_inq_dimid(ncid=ncRainID, name=time_names(indx), dimid=TimeDimID)
                !
                ! If found we get the length and VarID out
                if (status == nf90_noerr) then
                  !
                  status = nf90_inquire_dimension(ncid=ncRainID, dimid=TimeDimID, len=ntime)
                  status = nf90_inq_varid(ncid=ncRainID, name=time_names(indx), varid=TimeVarID)
                  !
                  allocate(time_coord(ntime))
                  status = nf90_get_var(ncid=ncRainID, varid=LonVarID, values=time_coord)
                  !
                  print *, 'NetCDF Status: found rainfall forcing file of len --> ', ntime
                  allocate(grid_clim(nlon,nlat,ntime))
                  allocate(rainfall(nxy,ntime))
                  if (nsteps == 0) then
                    nsteps = ntime
                  end if
                  exit
                elseif((indx == size(time_names)) .and. (status /= nf90_noerr)) then
                  print *, 'NetCDF Status: time dimension not indentified'
                  STOP
                end if
              end do
        
      
              ! Inquire about rainfall and get its VarID
              do indx=1,size(rain_names)
                  status = nf90_inq_varid(ncid=ncRainID, name=rain_names(indx), varid=RainVarID)
                  
                  ! If name is found exit do loop
                  if (status == nf90_noerr) then
                    print *, 'NetCDF Status: found rainfall variable of name --> ', rain_names(indx)
                    !
                    exit
                  else if((indx == size(rain_names)) .and. (status /= nf90_noerr)) then
                    print *, 'NetCDF Status: rainfall variable not indentified'
                    STOP
                  end if
              end do
              !
              ! Get rainfall values
              status = nf90_get_var(ncid=ncRainID, varid=RainVarID, values=grid_clim)
              !
              rainfall = reshape(grid_clim, (/nxy,ntime/))
              !
              ! Inquire attributes from "time" dimension and "rainfall" variable
              do indx=1,size(att_names)
                  status = nf90_get_att(ncid=ncRainID, varid=RainVarID, name=att_names(indx), values=rain_att(indx))
                  status = nf90_get_att(ncid=ncRainID, varid=TimeVarID, name=att_names(indx) , values=time_att(indx))
              end do
              !
              status = nf90_get_att(ncid=ncRainID, varid=RainVarID, name="_FillValue", values=FillValue_rain) 
              !
              !
              where(rainfall(:,1) == FillValue_rain) mask_pop = .false.  ! Do not simulate over missing rainfall points
              !
              deallocate(grid_clim)
              

        else  ! If not rainfall input set to zero 
          !
          allocate(rainfall(nxy,nsteps))
          rainfall(:,:) = 0
          !
        end if 


        if (out_t2m) then

              ! We need to extract the dates of the forcing and its total length, ntime, so that
              ! nsteps <= ntime.

              ! Open file
              status = nf90_open(path = t2m_file, mode = nf90_nowrite, ncid = ncTempID)

              ! Inquire about time and get its DimID 
              !
              do indx=1,size(time_names)
                !
                status = nf90_inq_dimid(ncid=ncTempID, name=time_names(indx), dimid=TimeDimID)
                !
                ! If found we get the length and VarID out
                if (status == nf90_noerr) then
                  !
                  status = nf90_inquire_dimension(ncid=ncTempID, dimid=TimeDimID, len=ntime)
                  status = nf90_inq_varid(ncid=ncTempID, name=time_names(indx), varid=TimeVarID)
                  !
                  if (size(time_coord) .ne. ntime) then
                    print *, 'Rainfall and temperature fields have different lenght --> Stop.' 
                    STOP
                  end if
                  !
                  status = nf90_get_var(ncid=ncTempID, varid=LonVarID, values=time_coord)
                  !
                  print *, 'NetCDF Status: found temperature forcing file of len --> ', ntime
                  allocate(grid_clim(nlon,nlat,ntime))
                  allocate(t2m(nxy,ntime))
                  if (nsteps == 0) then 
                    nsteps = ntime
                  end if 
                  exit
                elseif((indx == size(time_names)) .and. (status /= nf90_noerr)) then
                  print *, 'NetCDF Status: time dimension not indentified'
                  STOP
                end if
              end do
        
      
              ! Inquire about temperature and get its VarID
              do indx=1,size(temp_names)
                  status = nf90_inq_varid(ncid=ncTempID, name=temp_names(indx), varid=TempVarID)
                  
                  ! If name is found exit do loop
                  if (status == nf90_noerr) then
                    print *, 'NetCDF Status: found temperature variable of name --> ', temp_names(indx)
                    !
                    exit
                  else if((indx == size(temp_names)) .and. (status /= nf90_noerr)) then
                    print *, 'NetCDF Status: temperature variable not indentified'
                    STOP
                  end if
              end do
              !
              ! Get temperature values
              status = nf90_get_var(ncid=ncTempID, varid=TempVarID, values=grid_clim)
              !
              t2m = reshape(grid_clim, (/nxy,ntime/))
              !
              ! Inquire attributes from "t2m" variable (time attributes are taken from rainfall file)
              do indx=1,size(att_names)
                  status = nf90_get_att(ncid=ncTempID, varid=TempVarID, name=att_names(indx), values=temp_att(indx))
              end do
              !
              status = nf90_get_att(ncid=ncTempID, varid=TempVarID, name="_FillValue", values=FillValue_temp) 
              !
              where(t2m(:,1) == FillValue_temp) mask_pop = .false.  ! Do not simulate over missing temperature points
              !
              deallocate(grid_clim)

        else  ! If not temperature input set to zero --> Needs to be changed

          allocate(t2m(nxy,nsteps))
          t2m(:,:) = 0


        end if

        if (agents) then

              ! We need to extract the dates of the forcing and its total length, ntime, so that
              ! nsteps <= ntime.

              ! Open file
              status = nf90_open(path = area_file, mode = nf90_nowrite, ncid = ncAreaID)        
      
              ! Inquire about rainfall and get its VarID
              do indx=1,size(area_names)
                  status = nf90_inq_varid(ncid=ncAreaID, name=area_names(indx), varid=AreaVarID)
                  
                  ! If name is found exit do loop
                  if (status == nf90_noerr) then
                    print *, 'NetCDF Status: found area variable of name --> ', area_names(indx)
                    !
                    exit
                  else if((indx == size(area_names)) .and. (status /= nf90_noerr)) then
                    print *, 'NetCDF Status: area variable not indentified'
                    STOP
                  end if
              end do
              !
              ! Get cell area values
              status = nf90_get_var(ncid=ncAreaID, varid=AreaVarID, values=grid)
              !
              allocate(A_cell(nxy))
              A_cell = reshape(grid, (/nxy/))
              !

        else  ! If not rainfall input set to zero 
          !
          !allocate(rainfall(nxy,nsteps))
          !rainfall(:,:) = 0
          !
        end if
    
        deallocate(grid)
        

      end subroutine netcdf_read_grid



end MODULE mo_netcdf