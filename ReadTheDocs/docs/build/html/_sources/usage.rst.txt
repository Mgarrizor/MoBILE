Usage
=====

.. _installation:   
   
..
   This a comment!

Installation
------------

GitHub repository
^^^^^^^^^^^^^^^^^

The program is hosted by `GitHub <https://github.com/>`_. To use **MoBILE**, first *git clone* the program's repository typing the following in the command line:

.. code-block:: console

   git clone https://github.com/Mgarrizor/MoBILE.git

The main folders of interest are

**src**:

**utils**:


.. _env_var:   

Environmental variables
^^^^^^^^^^^^^^^^^^^^^^^

.. _netcdf_fortran:

The *Makefile* 

.. code-block:: console

   shell nf-config --fc

.. code-block:: console

   nf-config --fflags

.. code-block:: console

   nf-config --flibs


In order to avoid messing up your GitHub repository the program is made to be run in a folder different than the one where *MoBILE.git* is located. We thus need to let the program know where to find the former. For this, set the following environmental variable

.. code-block:: console

   export MOBILE=/path/to/MoBILE/.git

Now try 

.. code-block:: console

   ls $MOBILE

The command should return a list containing the *Makefile*, the **utils** and **src** folders, the **ReadTheDocs** used to create this documentation, two markdown (*README.md* and *LICENSE.md*) files and a bash script called *mobile.sh*, necessary to run the program. If that is the case you are now ready for your first run!

.. _first_run: 

First run
---------


.. _post_process: 

Post-processing
---------------


Second run
----------

Parameter tuning
^^^^^^^^^^^^^^^^

What's next?
------------







