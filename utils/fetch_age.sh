#!/bin/bash

# Bash script to download an analyse age structure
# =========================================================
# It creates 
# - A folder 'age_structure' with the original GeoTiff
#   files (in 'GeoTiff'folder) of the rasterized age structures 
#   in a givne country & a corresponding NetCDF file (in 'NetCDF' 
#   folder).
# - 3 figures to asses the sex ratios, spatial
#   homogeneity assumption and the interpolation between
#   age caterogories.
# - a 'cumm_age.txt' file with the weights of each age in
#   intervals of 1 year (ABM resolution).
# ==========================================================

# Country codes - Senegal: 'sen'

# Age codes - '00': from 0 to 12 months
#             '01':      1 to  4 years
#             '05':      5 to  9 years
#              10,15,20,25,30,35,40,45,50,55,60,65,70,75,
#             '80':      80 years or over
#
#              'f': female  'm': male
#--------------------------------------------------------
country1='SEN'                                             # Country code
country2='sen'
year=2020                                                  # Available years are 2020
ages=(0 1 5 10 15 20 25 30 35 40 45 50 55 60 65 70 75 80)  # This is hardcoded WorldPop age structure resolution
DIRECTORY="age_structure"

if [ ! -d "$DIRECTORY" ]; then

    mkdir -p ${DIRECTORY} && cd ${DIRECTORY}
    echo 'Downloading age files'
    for age in ${ages[@]}; do
        echo 'Age:' $age
        # Female
        wget -q https://data.worldpop.org/GIS/AgeSex_structures/Global_2000_2020_Constrained_UNadj/2020/${country1}//${country2}_f_${age}_${year}_constrained_UNadj.tif
        gdal_translate -q -of NetCDF ${country2}_f_${age}_${year}_constrained_UNadj.tif ${country2}_f_${age}_${year}_constrained_UNadj.nc
        # Male
        wget -q https://data.worldpop.org/GIS/AgeSex_structures/Global_2000_2020_Constrained_UNadj/2020/${country1}//${country2}_m_${age}_${year}_constrained_UNadj.tif
        gdal_translate -q -of NetCDF ${country2}_m_${age}_${year}_constrained_UNadj.tif ${country2}_m_${age}_${year}_constrained_UNadj.nc
    done
    
    mkdir -p 'GeoTiff'
    mkdir -p 'NetCDF'

    mv *.nc NetCDF/ 
    mv *.tif GeoTiff/
    cd ..
fi

if [ ! -f "$DIRECTORY/cumm_age.txt" ]; then
echo ' Processing age structure'

cd ${DIRECTORY}
python3 <<EOF
import xarray as xr
import numpy as np
import matplotlib.pyplot as plt
import scipy 

ages=[1, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80]

# Female population
ds_f = xr.open_dataset(f'NetCDF/${country2}_f_0_${year}_constrained_UNadj.nc')['Band1']
# Male population
ds_m = xr.open_dataset(f'NetCDF/${country2}_m_0_${year}_constrained_UNadj.nc')['Band1']
for a in ages:
    ds_dummy = xr.open_dataset(f'NetCDF/${country2}_f_{a}_${year}_constrained_UNadj.nc')['Band1']
    ds_f += ds_dummy
    ds_dummy = xr.open_dataset(f'NetCDF/${country2}_m_{a}_${year}_constrained_UNadj.nc')['Band1']
    ds_m += ds_dummy


# ============= Figure 1 ====================
#print('Spatial heterogeneity ...')
fig,ax = plt.subplots(6,3, sharex = True, sharey = True, dpi = 100)
ages=[0, 1, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80]
stats=np.zeros((len(ages),2))
nbins=20
ax = ax.flatten()

for i,a in enumerate(ages):
    plt.subplot(6,3,i+1)

    ds_dummy = xr.open_dataset(f'NetCDF/${country2}_f_{a}_${year}_constrained_UNadj.nc')['Band1']
    x_f =  (np.array(ds_dummy/ds_f)).flatten()
    hist, bins, _ = plt.hist(x_f, bins=nbins, range=(0,0.5), edgecolor = "k", facecolor = "none")
    hist, bins, _ = plt.hist(x_f, bins=nbins, range=(0,0.5), edgecolor = "k", facecolor = 'orange', alpha = 0.3)   

    ds_dummy = xr.open_dataset(f'NetCDF/${country2}_m_{a}_${year}_constrained_UNadj.nc')['Band1'] 
    x_m =  (np.array(ds_dummy/ds_m)).flatten()
    hist, bins, _ = plt.hist(x_m, bins=nbins, range=(0,0.5), edgecolor = "k", facecolor = "none")
    hist, bins, _ = plt.hist(x_m, bins=nbins, range=(0,0.5), edgecolor = "k", facecolor = 'skyblue', alpha = 0.3)   
    plt.text(0.3,np.max(hist)*0.25,a)
    plt.grid(alpha=0.4) 
    stats[i] = np.mean(x_f[~np.isnan(x_f)]), np.mean(x_m[~np.isnan(x_m)])

plt.tight_layout()
plt.savefig('spatial_heterogeneity.pdf',dpi = 100)
plt.close()

# ============= Figure 2 ====================
#print('Sex ratios ...')

ages_shift = 0.5*(np.roll(np.array(ages),-1)+np.array(ages))#[:-1]
ages_shift[-1] = ages_shift[-1]*2
ages_shift[0] = 0

plt.plot(ages_shift,stats[:,0],"-o", label = "Female")
plt.plot(ages_shift,stats[:,1],"-o", label = "Male")

plt.ylabel("Fraction")
plt.xlabel("Ages [year]")
plt.grid(alpha=0.4)
plt.tight_layout()

plt.ylabel("Fraction")
plt.xlabel("Ages [year]")
plt.grid(alpha=0.4)
plt.tight_layout()
plt.legend(fontsize = 20)

plt.savefig('sex_ratios.pdf',dpi = 100)
plt.close()

# ============= Figure 3 ====================
#print('Interpolation of weights ...')

mean_stats = np.mean(stats, axis=1)
ages_model = np.arange(int(np.floor(np.min(ages_shift))), int(np.ceil(np.max(ages_shift)))+1)

splines = scipy.interpolate.make_interp_spline(ages_shift,np.cumsum(mean_stats), k = 3)
y_new = splines(ages_model).T

plt.subplots(dpi=100, sharey = False)

plt.plot(ages_model, y_new, '-o', color = 'red',ms = 2.5, alpha = 0.4)
plt.scatter(ages_shift,np.cumsum(mean_stats), s=70, color = 'purple', edgecolor = 'k', alpha = 0.4)

plt.xlabel("Age [year]")
plt.ylabel("Cummulative summation of weights [age]")
plt.grid(alpha=0.4)
plt.tight_layout()
plt.yscale('log')

plt.savefig('interpolation.pdf',dpi = 100)
plt.close()

#================= Save cummulative array =======
np.savetxt('cumm_age.txt', y_new, fmt='%.3f', delimiter=' ', newline='\n', header='', footer='', comments='# ', encoding=None)
EOF
fi










