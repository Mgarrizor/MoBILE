Model description
=================



People representation
---------------------

Density
^^^^^^^

Agents
^^^^^^

Each agent describes a group of people, given by their age, sex, socio-economic characteristics, etc, which are set as :ref:`attributes <attributes>` of that agent. The number of agents in a given location, :math:`N_i`, is the proportion of the total population present in that location, :math:`\rho_i/\sum_j \rho_j`, times the total number of agents :math:`N_{tot}` of a given simulation, this is,

.. math::

    N_i = \frac{\rho_i}{\sum_j \rho_j} \cdot N_{tot} \ .


:math:`N_{tot}` is a free parameter with the constraint

.. math::

    N_{tot} \le \sum_j \rho_j \cdot A_j \ ,


where :math:`A_j` is the area of the grid cell. This is a way to ensure no more agents than actual people are simulated. In the limit where the number of agents matches the actual number of people in a region each agent then describes a single individual. The total number of agents is kept constant throughout the course of a simulation. To convert numbers back into densities, *e.g*., the number of infected people at a given location, :math:`i_i`, we just apply the conversion backwards, *i.e*.,

.. math::

    i_i = \frac{I_i}{N_{tot}} \cdot \sum_j \rho_j \ .



At any given time, each agent can either be *dead* or *alive*. When *dead*, the agent is inactive until a growth event occurs, after which the agent becomes *alive*. When *alive*, agents area active and each time step might undergo a set of events, each with a given probability. The set depends on the agent's infected status (*e.g*., for cholera, *S*: susceptible, *I*: infected, *A*: asymptomatic and *R*: recovered) and probabilities might change based on some of the agent's attributes. An event based on mobility, for example, might be less likely if the agent is *old* and rarely moves.


.. _attributes: 

**Attributes** 



Climatic forcings
-----------------



Diseases
--------


Cholera
^^^^^^^


Malaria - VECTRI
^^^^^^^^^^^^^^^^

A coupling with `VECTRI <https://users.ictp.it/~tompkins/vectri/documentation/>`_ is under active development and malaria is thus not yet functional.

