#!/home/ac.ngmahfouz/.micromamba/envs/xgns/bin/python
"""
Prepare SPA file(s) for SCREAM runs
    1. Make SPA files based entirely on EAMv2 experiments
    2. Make SPA file by using the ratio from EAMv2 experiments
"""

import os
import subprocess
import numpy as np
import xarray as xr


BASE_DIR = "/lcrc/group/e3sm/ac.ngmahfouz/v2.LR"
NCCLIMO_CMD = "/home/ac.ngmahfouz/.micromamba/envs/xgns/bin/ncclimo"
NCKS_CMD = "/home/ac.ngmahfouz/.micromamba/envs/xgns/bin/ncks"
PD_EXP = "run.v2.LR.F2010.ospa"
PI_EXP = "run.v2.LR.F2010.pi.ospa"

data_dict = {}

for exp in [PD_EXP, PI_EXP]:
    # cd into experiment folder
    os.chdir(f"{BASE_DIR}/{exp}/post/atm/")
    # make native h7 folder
    subprocess.run("mkdir -p native_h7", shell=True, check=True)
    # perform ncclimo
    subprocess.run(
        f"{NCCLIMO_CMD} "
        f"-v CCN3M,AER_G_SW,AER_SSA_SW,AER_TAU_LW,AER_TAU_SW "
        f"-h h7 -s 2010 -e 2039 "
        f"-c {exp} "
        f"-i {BASE_DIR}/{exp}/archive/atm/hist -o native_h7",
        shell=True,
        check=True,
    )
    # load h7 climo data
    data_dict[f"{exp}_h7"] = xr.open_mfdataset(
        f"{BASE_DIR}/{exp}/post/atm/native_h7/{exp}_??_*.nc"
    ).load()
    # load h0 climo data (only PS and area)
    data_dict[f"{exp}_h0"] = xr.open_mfdataset(
        f"{BASE_DIR}/{exp}/post/atm/native/clim/30yr/{exp}_??_*.nc"
    )[["PS", "area"]].load()
    # merge h7 and h0 data
    data_dict[exp] = xr.merge(
        [data_dict[f"{exp}_h0"], data_dict[f"{exp}_h7"]]
    )
    # rename CCN3M to CCN3
    data_dict[exp] = data_dict[exp].rename_vars({"CCN3M": "CCN3"})
    # transpose dims to conform with scream reqs
    data_dict[exp] = data_dict[exp].transpose(
        "time", "ncol", "lwband", "swband", "nbnd", "ilev", "lev"
    )
    # save to netcdf4 format (saving to cdf5 is too slow)
    data_dict[exp].to_netcdf(f"{BASE_DIR}/{exp}/post/atm/{exp}.nc")
    # use ncks to convert to cdf5
    subprocess.run(
        f"{NCKS_CMD} -5 "
        f"{BASE_DIR}/{exp}/post/atm/{exp}.nc "
        f"{BASE_DIR}/{exp}/post/atm/{exp}.nc.cdf5",
        shell=True,
        check=True,
    )
    # move cdf5 to nc to finish
    subprocess.run(
        f"mv "
        f"{BASE_DIR}/{exp}/post/atm/{exp}.nc.cdf5 "
        f"{BASE_DIR}/{exp}/post/atm/{exp}.nc",
        shell=True,
        check=True,
    )

# a handy empty dict
exps_dict = {}
# the vars we want ratios of...
SPAO_VARS = [
    "PS",
    "CCN3",
    "AER_G_SW",
    "AER_SSA_SW",
    "AER_TAU_LW",
    "AER_TAU_SW"
]
E3SM_INPUTDATA_DIR = "/lcrc/group/e3sm/data/inputdata"
DEF_SPA_FILE = "spa_file_unified_and_complete_ne30pg2_20240111"
# load the data
for exp in [PD_EXP, PI_EXP]:
    exps_dict[exp] = xr.open_dataset(
        f"{BASE_DIR}/{exp}/post/atm/{exp}.nc"
    ).load()
# compute ratio
# note we set the ratio to 0 if the numerator is 0
for spao_var in SPAO_VARS:
    exps_dict[f"ratio_{spao_var}"] = (
        exps_dict[PI_EXP][spao_var] / exps_dict[PD_EXP][spao_var]
    ).where(exps_dict[PD_EXP][spao_var] != 0, 0.0)
# load the current default spa file
default_spa = xr.open_dataset(
    f"{E3SM_INPUTDATA_DIR}/atm/scream/init/"
    f"{DEF_SPA_FILE}.nc"
).load()
# copy the default spa file (to avoid overwriting)
new_pi_spa = default_spa.copy()
# update the new spa file with the computed ratios
for spao_var in SPAO_VARS:
    new_pi_spa[spao_var] = (
        default_spa[spao_var].dims,
        default_spa[spao_var].values*exps_dict[f"ratio_{spao_var}"].values
    )
# some (weak) checks follow:
# to ensure that this procedure is numerically accurate
# but obviously not deterministically so
for spao_var in SPAO_VARS:
    if spao_var == "CCN3":
        rtol_, atol_ = 1e-7, 10
    else:
        rtol_, atol_ = 1e-6, 1e-3
    np.testing.assert_allclose(
        exps_dict[f"ratio_{spao_var}"] * exps_dict[PD_EXP][spao_var],
        exps_dict[PI_EXP][spao_var],
        rtol=rtol_, atol=atol_, verbose=True
    )
# to mainly ensure consistency in how data is stored
for spao_var in SPAO_VARS:
    if spao_var == "CCN3":
        rtol_, atol_ = 1e-6, 1e10
    elif spao_var == "PS":
        rtol_, atol_ = 1e-6, 1e6
    else:
        rtol_, atol_ = 1e-6, 1e6
    np.testing.assert_allclose(
        new_pi_spa[spao_var], exps_dict[PI_EXP][spao_var],
        rtol=rtol_, atol=atol_, verbose=True
    )
# to ensure that this the default spa and new ones
# are close to each other numerically, but
# obviously not deterministically so
for spao_var in SPAO_VARS:
    if spao_var in ["CCN3", "PS"]:
        rtol_, atol_ = 1e-7, 1e9
    else:
        rtol_, atol_ = 1e-6, 1
    np.testing.assert_allclose(
        default_spa[spao_var],
        exps_dict[PD_EXP][spao_var],
        rtol=rtol_, atol=atol_, verbose=True
    )
# if all weak checks pass, then let's save it
new_pi_spa.to_netcdf(
    f"{BASE_DIR}/{PI_EXP}/post/atm/"
    f"{DEF_SPA_FILE}_pi.nc"
)
# use ncks to convert to cdf5
subprocess.run(
    f"{NCKS_CMD} -5 "
    f"{BASE_DIR}/{PI_EXP}/post/atm/"
    f"{DEF_SPA_FILE}_pi.nc "
    f"{BASE_DIR}/{PI_EXP}/post/atm/"
    f"{DEF_SPA_FILE}_pi.nc.cdf5",
    shell=True,
    check=True,
)
# move cdf5 to nc to finish
subprocess.run(
    f"mv "
    f"{BASE_DIR}/{PI_EXP}/post/atm/"
    f"{DEF_SPA_FILE}_pi.nc.cdf5 "
    f"{BASE_DIR}/{PI_EXP}/post/atm/"
    f"{DEF_SPA_FILE}_pi.nc",
    shell=True,
    check=True,
)
