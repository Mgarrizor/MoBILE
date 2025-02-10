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

            status = nf90_put_var(ncid = ncid_out, varid = VarId(var_out), & 
                                  values = reshape((pop_dens), shape = (/ nlon, nlat /)))
            var_out = var_out + 1
            if(status /= nf90_noerr) then
              print *, 'NetCDF Status Pop'
              STOP
            end if

        end if 

        if ((out_Q)) then            
            
            status = nf90_put_var(ncid = ncid_out, varid = VarId(var_out), & 
                                  values = reshape((Q(xy_seed,:)), shape = (/ nlon, nlat /)))
            var_out = var_out + 1

        end if 

        if ((out_D)) then            
           
            status = nf90_put_var(ncid = ncid_out, varid = VarId(var_out), & 
                                 values = reshape((dist(xy_seed,:)), shape = (/ nlon, nlat /)))
            var_out = var_out + 1
        end if 

        status = nf90_close(ncid_out)

      end subroutine netcdf_2D_output

      subroutine netcdf_3D_output(itime,Var3D)
        implicit none
        integer, intent(in) :: itime, Var3D

        ! Local use
        integer :: var_out,status

        ! 3D Fields
        var_out = Var3D
        if ((out_S)) then
            
            status = nf90_put_var(ncid = ncid_out, varid = VarId(var_out), & 
                                  values = reshape((S), shape = (/ nlon, nlat /)), &
                                  start = (/ 1, 1, itime /))
            var_out = var_out + 1

           if(status /= nf90_noerr) then
            print *, 'NetCDF Status S'
            print *, itime
            STOP
           end if

        end if 
        if ((out_I)) then
            
            status = nf90_put_var(ncid = ncid_out, varid = VarId(var_out), & 
                                  values = reshape((I), shape = (/ nlon, nlat /)), &
                                  start = (/ 1, 1, itime /))
            var_out = var_out + 1

        end if
        if ((out_A)) then
            
            status = nf90_put_var(ncid = ncid_out, varid = VarId(var_out), & 
                                  values = reshape((A), shape = (/ nlon, nlat /)), &
                                  start = (/ 1, 1, itime /))
            var_out = var_out + 1

        end if
        if ((out_R)) then
            
            status = nf90_put_var(ncid = ncid_out, varid = VarId(var_out), & 
                                  values = reshape((R), shape = (/ nlon, nlat /)), &
                                  start = (/ 1, 1, itime /))
            var_out = var_out + 1

        end if
        if ((out_B)) then
            
            status = nf90_put_var(ncid = ncid_out, varid = VarId(var_out), & 
                                  values = reshape((B), shape = (/ nlon, nlat /)), &
                                  start = (/ 1, 1, itime /))
            var_out = var_out + 1
            if(status /= nf90_noerr) then
              print *, 'NetCDF Status B'
              STOP
            end if

        end if
        if ((out_F)) then
            
            status = nf90_put_var(ncid = ncid_out, varid = VarId(var_out), & 
                                  values = reshape((F), shape = (/ nlon, nlat /)), &
                                  start = (/ 1, 1, itime /))
            var_out = var_out + 1
            

        end if

        ! ============================== Climate ======================================

        if ((out_rain)) then

            status = nf90_put_var(ncid = ncid_out, varid = VarId(var_out), & 
                                  values = reshape((rainfall(:,itime)), shape = (/ nlon, nlat /)), &
                                  start = (/ 1, 1, itime /))
            var_out = var_out + 1

        end if 

      end subroutine netcdf_3D_output


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

        integer :: status, indx
        integer :: var_out=1, dim


        ! Horrible, clean it up!
        ! Lon+Lat+Time+ Rest
        dim = 3 + merge(1, 0, out_pop)+merge(1, 0, out_S)+merge(1, 0, out_E) &
                                      +merge(1, 0, out_I)+merge(1, 0, out_R) &
                                      +merge(1, 0, out_B)+merge(1, 0, out_F) &
                                      +merge(1, 0, out_A)+merge(1, 0, out_Q) &
                                      +merge(1, 0, out_D)+merge(1, 0, out_rain)

        allocate(VarId(dim))
        ! returns a netCDF ID that can subsequently be used 
        ! to refer to the netCDF dataset in other netCDF function calls

        ! Create new dataset and assign main spatial dimensions
        status = nf90_create(path=trim(run_name)//".nc", cmode = 0, ncid = ncid_out)
        
        status = nf90_def_dim(ncid = ncid_out, name = "lon", len = nlon,   dimid = DimId(1))
        status = nf90_def_dim(ncid = ncid_out, name = "lat", len = nlat,   dimid = DimId(2))
        status = nf90_def_dim(ncid = ncid_out, name = "time",len = nsteps, dimid = DimId(3))
        
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
        ! We write time attributes in the 3D field along the climatic forcings

        
        ! Define variables and assign attributes and values
        ! Constrain: order should be the same of def_var!
        ! 2D Fields (x,y) (no time) --------------------------------------------
        if ((out_pop)) then

            VarId(var_out)=var_out
            status = nf90_def_var(ncid = ncid_out, name = "pop", xtype = nf90_double, &
                      dimids = (/ DimId(1), DimId(2) /), varid = VarId(var_out))
            status = nf90_put_att(ncid = ncid_out, varid = VarId(var_out), name = "units", values = "km^-2")
            status = nf90_put_att(ncid = ncid_out, varid = VarId(var_out), name = "_FillValue", values = FillValue)
            status = nf90_def_var_fill(ncid_out, VarId(var_out), 0, FillValue)
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


        ! 3D Fields (x,y,t)
        Var3D = var_out

        ! ============================== Human ======================================
        if ((out_S)) then

            VarId(var_out)=var_out
            status = nf90_def_var(ncid = ncid_out, name = "S", xtype = nf90_double, &
                      dimids = (/ DimId(1), DimId(2), DimId(3)/), varid = VarId(var_out))
            status = nf90_put_att(ncid = ncid_out, varid = VarId(var_out), name = "units", values = "km^-2")
            status = nf90_put_att(ncid = ncid_out, varid = VarId(var_out), name = "long_name", values = "Susceptible population density")
            var_out = var_out + 1

        end if

        if ((out_I)) then

            VarId(var_out)=var_out
            status = nf90_def_var(ncid = ncid_out, name = "I", xtype = nf90_double, &
                      dimids = (/ DimId(1), DimId(2), DimId(3)/), varid = VarId(var_out))
            status = nf90_put_att(ncid = ncid_out, varid = VarId(var_out), name = "units", values = "km^-2")
            status = nf90_put_att(ncid = ncid_out, varid = VarId(var_out), name = "long_name", values = "Infected symptomatic population density")
            var_out = var_out + 1

        end if

        if ((out_A)) then

            VarId(var_out)=var_out
            status = nf90_def_var(ncid = ncid_out, name = "A", xtype = nf90_double, &
                      dimids = (/ DimId(1), DimId(2), DimId(3)/), varid = VarId(var_out))
            status = nf90_put_att(ncid = ncid_out, varid = VarId(var_out), name = "units", values = "km^-2")
            status = nf90_put_att(ncid = ncid_out, varid = VarId(var_out), name = "long_name", values = "Infected asymptomatic population density")
            var_out = var_out + 1

        end if

        if ((out_R)) then

            VarId(var_out)=var_out
            status = nf90_def_var(ncid = ncid_out, name = "R", xtype = nf90_double, &
                      dimids = (/ DimId(1), DimId(2), DimId(3)/), varid = VarId(var_out))
            status = nf90_put_att(ncid = ncid_out, varid = VarId(var_out), name = "units", values = "km^-2")
            status = nf90_put_att(ncid = ncid_out, varid = VarId(var_out), name = "long_name", values = "Recovered population density")
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

        if ((out_rain)) then


          VarId(var_out)=var_out
          status = nf90_def_var(ncid = ncid_out, name = "rain", xtype = nf90_double, &
                    dimids = (/ DimId(1), DimId(2) , DimId(3) /), varid = VarId(var_out))
          !status = nf90_put_att(ncid = ncid_out, varid = VarId(var_out), name = "_FillValue", values = FillValue_rain)
          !status = nf90_def_var_fill(ncid_out, VarId(var_out), 0, FillValue_rain)

          !print *, FillValue_rain
          
          
          ! Write rainfall attributes
          do indx=1,size(att_names)
              !
              if (len(trim(rain_att(indx))) /= 0) then 
                status = nf90_put_att(ncid=ncid_out, varid = VarId(var_out), name=att_names(indx), values=rain_att(indx))
              end if
              !
          end do
            !
          var_out = var_out + 1
        end if


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

      subroutine netcdf_read_grid(pop_file,grid,nlon,nlat,nxy,pop_dens,lon_coord,lat_coord,mask_pop)
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
        character(len=100) :: long_lat
        integer, intent(out) :: nlon, nlat, nxy
        real, allocatable, intent(out) :: pop_dens(:)
        real, allocatable, intent(out) :: lon_coord(:)
        real, allocatable, intent(out) :: lat_coord(:)
        real, allocatable, intent(out) :: grid(:,:)
        logical, allocatable, intent(out) :: mask_pop(:)

        ! Rainfall --------------------------
        !character(len=100), intent(in) :: rain_file
        !real, allocatable, intent(out) :: rainfall(:)

        ! Local use only 
        integer :: TimeVarID, TimeDimID, RainVarID, indx_rain
        ! -----------------------------------

        ! Local use only
        integer :: status, LatDimID, LonDimID, LatVarID, LonVarID, PopVarID
        integer :: numdims, indx_lat, indx_lon, indx_pop, indx

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

        status = nf90_get_att(ncid=ncid_in, varid=PopVarID, name="_FillValue", values=fill_pop) 

        ! Get variable values
        status = nf90_get_var(ncid=ncid_in, varid=LatVarID, values=lat_coord)
        status = nf90_get_var(ncid=ncid_in, varid=LonVarID, values=lon_coord)

        ! Get variables and set them to a standard missing value where = to attribute _FillValue
        ! https://docs.unidata.ucar.edu/netcdf-fortran/current/f90-variables.html#f90-fill-values
        status = nf90_get_var(ncid=ncid_in, varid=PopVarID, values=grid)

        pop_dens = reshape(grid, (/nxy/))

        where(pop_dens == fill_pop) pop_dens = 0.
        where(pop_dens < eps) pop_dens = 0.

        where(pop_dens < 1.) pop_dens = 0.  ! Yemen 

        where(pop_dens < eps) mask_pop = .false.
        where(pop_dens > eps) mask_pop = .true.

        where(pop_dens > eps) D = 1/log(pop_dens+1)

        if (out_rain) then

              ! We need to extract the dates of the forcing and its total length, ntime, so that
              ! nsteps <= ntime.

              ! Open file
              status = nf90_open(path = rain_file, mode = nf90_nowrite, ncid = ncid_in)

              ! Inquire about time and get its DimID 
              !
              do indx=1,size(time_names)
                !
                status = nf90_inq_dimid(ncid=ncid_in, name=time_names(indx), dimid=TimeDimID)
                !
                ! If found we get the length and VarID out
                if (status == nf90_noerr) then
                  !
                  status = nf90_inquire_dimension(ncid=ncid_in, dimid=TimeDimID, len=ntime)
                  status = nf90_inq_varid(ncid=ncid_in, name=time_names(indx), varid=TimeVarID)
                  !
                  allocate(time_coord(ntime))
                  status = nf90_get_var(ncid=ncid_in, varid=LonVarID, values=time_coord)
                  !
                  print *, 'NetCDF Status: found rainfall forcing file of len --> ', ntime
                  allocate(grid_clim(nlon,nlat,ntime))
                  allocate(rainfall(nxy,ntime))
                  exit
                elseif((indx == size(pop_names)) .and. (status /= nf90_noerr)) then
                  print *, 'NetCDF Status: time dimension not indentified'
                  STOP
                end if
              end do
        
      
              ! Inquire about rainfall and get its VarID
              do indx=1,size(rain_names)
                  status = nf90_inq_varid(ncid=ncid_in, name=rain_names(indx), varid=RainVarID)
                  
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
              status = nf90_get_var(ncid=ncid_in, varid=RainVarID, values=grid_clim)
              !
              rainfall = reshape(grid_clim, (/nxy,ntime/))
              !
              ! Inquire attributes from "time" dimension and "rainfall" variable
              do indx=1,size(att_names)
                  status = nf90_get_att(ncid=ncid_in, varid=RainVarID, name=att_names(indx), values=rain_att(indx))
                  status = nf90_get_att(ncid=ncid_in, varid=TimeVarID, name=att_names(indx) , values=time_att(indx))
              end do
              !
              status = nf90_get_att(ncid=ncid_in, varid=RainVarID, name="_FillValue", values=FillValue_rain) 
              !
              where(rainfall == FillValue_rain) rainfall = 0.

              deallocate(grid_clim)

        else  ! If not rainfall input set to zero 
          allocate(rainfall(nxy,nsteps))
          rainfall(:,:) = 0


        end if 

        deallocate(grid)
        

      end subroutine netcdf_read_grid



end MODULE mo_netcdf