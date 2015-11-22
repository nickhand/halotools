# -*- coding: utf-8 -*-
"""
Module storing the various factories used to build galaxy-halo models. 
"""

__all__ = ['ModelFactory', 'HodModelArchitect']
__author__ = ['Andrew Hearin']

import numpy as np
from copy import copy
from functools import partial
from astropy.extern import six
from abc import ABCMeta, abstractmethod, abstractproperty
from warnings import warn 

from .hod_mock_factory import HodMockFactory
from .subhalo_mock_factory import SubhaloMockFactory

from .. import model_helpers
from .. import model_defaults 

from ...sim_manager.supported_sims import HaloCatalog
from ...sim_manager import sim_defaults
from ...sim_manager.generate_random_sim import FakeSim
from ...utils.array_utils import custom_len
from ...custom_exceptions import *

@six.add_metaclass(ABCMeta)
class ModelFactory(object):
    """ Abstract container class used to build 
    any composite model of the galaxy-halo connection. 
    """

    def __init__(self, input_model_dictionary, **kwargs):
        """
        Parameters
        ----------
        input_model_dictionary : dict 
            dictionary providing instructions for how to build the composite 
            model from a set of components. 

        galaxy_selection_func : function object, optional  
            Function object that imposes a cut on the mock galaxies. 
            Function should take a length-k Astropy table as a single positional argument, 
            and return a length-k numpy boolean array that will be 
            treated as a mask over the rows of the table. If not None, 
            the mask defined by ``galaxy_selection_func`` will be applied to the 
            ``galaxy_table`` after the table is generated by the `populate_mock` method. 
            Default is None.  

        halo_selection_func : function object, optional   
            Function object used to place a cut on the input ``table``. 
            If the ``halo_selection_func`` keyword argument is passed, 
            the input to the function must be a single positional argument storing a 
            length-N structured numpy array or Astropy table; 
            the function output must be a length-N boolean array that will be used as a mask. 
            Halos that are masked will be entirely neglected during mock population.
        """

        # Bind the model-building instructions to the composite model
        self._input_model_dictionary = input_model_dictionary

        try:
            self.galaxy_selection_func = kwargs['galaxy_selection_func']
        except KeyError:
            pass            

        try:
            self.halo_selection_func = kwargs['halo_selection_func']
        except KeyError:
            pass


    def populate_mock(self, **kwargs):
        """ Method used to populate a simulation using the model. 

        After calling this method, ``self`` will have a new ``mock`` attribute, 
        which has a ``table`` bound to it containing the Monte Carlo 
        realization of the model. 

        Parameters 
        ----------
        halocat : object, optional 
            Class instance of `~halotools.sim_manager.HaloCatalog`. 
            This object contains the halo catalog and its metadata.  

        simname : string, optional
            Nickname of the simulation. Currently supported simulations are 
            Bolshoi  (simname = ``bolshoi``), Consuelo (simname = ``consuelo``), 
            MultiDark (simname = ``multidark``), and Bolshoi-Planck (simname = ``bolplanck``). 
            Default is set in `~halotools.sim_manager.sim_defaults`. 

        halo_finder : string, optional
            Nickname of the halo-finder, e.g. ``rockstar`` or ``bdm``. 
            Default is set in `~halotools.sim_manager.sim_defaults`. 

        redshift : float, optional
            Redshift of the desired catalog. 
            Default is set in `~halotools.sim_manager.sim_defaults`. 

        """
        inconsistent_redshift_error_msg = ("Inconsistency between the model redshift = %.2f "
            "and the halocat redshift = %.2f.\n"
            "You should instantiate a new model object if you wish to switch halo catalogs.")
        inconsistent_simname_error_msg = ("Inconsistency between the simname "
            "already bound to the existing mock = ``%s`` "
            "and the simname passed as a keyword argument = ``%s``.\n"
            "You should instantiate a new model object if you wish to switch halo catalogs.")
        inconsistent_halo_finder_error_msg = ("Inconsistency between the halo-finder "
            "already bound to the existing mock = ``%s`` "
            "and the halo-finder passed as a keyword argument = ``%s``.\n"
            "You should instantiate a new model object if you wish to switch halo catalogs.")


        def test_consistency_with_existing_mock(**kwargs):
            if 'redshift' in kwargs:
                redshift = kwargs['redshift']
            elif 'halocat' in kwargs:
                redshift = kwargs['halocat'].redshift
            else:
                redshift = sim_defaults.default_redshift
            if abs(redshift - self.mock.halocat.redshift) > 0.05:
                raise HalotoolsError(inconsistent_redshift_error_msg % (redshift, self.mock.halocat.redshift))

            if 'simname' in kwargs:
                simname = kwargs['simname']
            elif 'halocat' in kwargs:
                simname = kwargs['halocat'].simname
            else:
                simname = sim_defaults.default_simname
            if simname != self.mock.halocat.simname:
                raise HalotoolsError(inconsistent_simname_error_msg % (self.mock.halocat.simname, simname))

            if 'halo_finder' in kwargs:
                halo_finder = kwargs['halo_finder']
            elif 'halocat' in kwargs:
                halo_finder = kwargs['halocat'].halo_finder
            else:
                halo_finder = sim_defaults.default_halo_finder
            if halo_finder != self.mock.halocat.halo_finder:
                raise HalotoolsError(inconsistent_halo_finder_error_msg % (self.mock.halocat.halo_finder,halo_finder ))

        if hasattr(self, 'mock'):
            test_consistency_with_existing_mock(**kwargs)
        else:
            if 'halocat' in kwargs.keys():
                halocat = kwargs['halocat']
                del kwargs['halocat'] # otherwise the call to the mock factory below has multiple halocat kwargs
            else:
                halocat = HaloCatalog(**kwargs)

            if hasattr(self, 'redshift'):
                if abs(self.redshift - halocat.redshift) > 0.05:
                    raise HalotoolsError("Inconsistency between the model redshift = %.2f" 
                        " and the halocat redshift = %.2f" % (self.redshift, halocat.redshift))

            mock_factory = self.mock_factory 
            self.mock = mock_factory(halocat=halocat, model=self, populate=False)


        self.mock.populate()

    def update_param_dict_decorator(self, component_model, func_name):
        """ Decorator used to propagate any possible changes in the composite model param_dict 
        down to the appropriate component model param_dict. 

        Parameters 
        -----------
        component_model : obj 
            Instance of the component model in which the behavior of the function is defined. 

        func_name : string 
            Name of the method in the component model whose behavior is being decorated. 

        Returns 
        --------
        decorated_func : function 
            Function object whose behavior is identical 
            to the behavior of the function in the component model, 
            except that the component model param_dict is first updated with any 
            possible changes to corresponding parameters in the composite model param_dict.

        See also 
        --------
        :ref:`update_param_dict_decorator_mechanism`

        :ref:`param_dict_mechanism`
        """

        def decorated_func(*args, **kwargs):

            # Update the param_dict as necessary
            for key in self.param_dict.keys():
                if key in component_model.param_dict:
                    component_model.param_dict[key] = self.param_dict[key]

            func = getattr(component_model, func_name)
            return func(*args, **kwargs)

        return decorated_func

    def compute_average_galaxy_clustering(self, num_iterations=5, summary_statistic = 'median', **kwargs):
        """
        Method repeatedly populates a simulation with a mock galaxy catalog, computes the clustering 
        signal of each Monte Carlo realization, and returns a summary statistic of the clustering 
        such as the median computed from the collection of clustering measurements. 

        Parameters 
        ----------
        num_iterations : int, optional 
            Number of Monte Carlo realizations to use to estimate the clustering signal. 
            Default is 5.

        summary_statistic : string, optional 
            String specifying the method used to estimate the clustering signal from the 
            collection of Monte Carlo realizations. Options are ``median`` and ``mean``. 
            Default is ``median``. 

        simname : string, optional 
            Nickname of the simulation into which mock galaxies will be populated. 
            Currently supported simulations are 
            Bolshoi  (simname = ``bolshoi``), Consuelo (simname = ``consuelo``), 
            MultiDark (simname = ``multidark``), and Bolshoi-Planck (simname = ``bolplanck``). 
            Default is set in `~halotools.sim_manager.sim_defaults`. 

        halo_finder : string, optional  
            Nickname of the halo-finder of the halocat into which mock galaxies 
            will be populated, e.g., `rockstar` or `bdm`. 
            Default is set in `~halotools.sim_manager.sim_defaults`. 

        desired_redshift : float, optional
            Redshift of the desired halocat into which mock galaxies will be populated. 
            Default is set in `~halotools.sim_manager.sim_defaults`. 

        variable_galaxy_mask : scalar, optional 
            Any value used to construct a mask to select a sub-population 
            of mock galaxies. See examples below. 

        mask_function : array, optional 
            Function object returning a masking array when operating on the galaxy_table. 
            More flexible than the simpler ``variable_galaxy_mask`` option because ``mask_function``
            allows for the possibility of multiple simultaneous cuts. See examples below. 

        include_crosscorr : bool, optional 
            Only for simultaneous use with a ``variable_galaxy_mask``-determined mask. 
            If ``include_crosscorr`` is set to False (the default option), method will return 
            the auto-correlation function of the subsample of galaxies determined by 
            the input ``variable_galaxy_mask``. If ``include_crosscorr`` is True, 
            method will return the auto-correlation of the subsample, 
            the cross-correlation of the subsample and the complementary subsample, 
            and the the auto-correlation of the complementary subsample, in that order. 
            See examples below. 

        rbins : array, optional 
            Bins in which the correlation function will be calculated. 
            Default is set in `~halotools.empirical_models.model_defaults` module. 

        Returns 
        --------
        rbin_centers : array 
            Midpoint of the bins used in the correlation function calculation 

        correlation_func : array 
            If not using any mask (the default option), method returns the 
            correlation function of the full mock galaxy catalog. 

            If using a mask, and if ``include_crosscorr`` is False (the default option), 
            method returns the correlation function of the subsample of galaxies determined by 
            the input mask. 

            If using a mask, and if ``include_crosscorr`` is True, 
            method will return the auto-correlation of the subsample, 
            the cross-correlation of the subsample and the complementary subsample, 
            and the the auto-correlation of the complementary subsample, in that order. 
            See the example below. 

        Examples 
        ---------
        The simplest use-case of the `compute_average_galaxy_clustering` function 
        is just to call the function with no arguments. This will generate a sequence 
        of Monte Carlo realizations of your model into the default halocat, 
        calculate the two-point correlation function of all galaxies in your mock, 
        and return the median clustering strength in each radial bin: 

        >>> model = Leauthaud11() # doctest: +SKIP 
        >>> r, clustering = model.compute_average_galaxy_clustering() # doctest: +SKIP 

        To control how which simulation is used, you use the same syntax you use to load 
        a `~halotools.sim_manager.HaloCatalog` into memory from your cache directory: 

        >>> r, clustering = model.compute_average_galaxy_clustering(simname = 'multidark', desired_redshift=1) # doctest: +SKIP 

        You can control the number of mock catalogs that are generated via: 

        >>> r, clustering = model.compute_average_galaxy_clustering(num_iterations = 10) # doctest: +SKIP 

        You may wish to focus on the clustering signal for a specific subpopulation. To do this, 
        you have two options. First, you can use the ``variable_galaxy_mask`` mechanism: 

        >>> r, clustering = model.compute_average_galaxy_clustering(gal_type = 'centrals') # doctest: +SKIP 

        With the ``variable_galaxy_mask`` mechanism, you are free to use any column of your galaxy_table 
        as a keyword argument. If you couple this function call with the ``include_crosscorr`` 
        keyword argument, the function will also return all auto- and cross-correlations of the subset 
        and its complement:

        >>> r, cen_cen, cen_sat, sat_sat = model.compute_average_galaxy_clustering(gal_type = 'centrals', include_crosscorr = True) # doctest: +SKIP 

        Your second option is to use the ``mask_function`` option. 
        For example, suppose we wish to study the clustering of satellite galaxies 
        residing in cluster-mass halos:

        >>> def my_masking_function(table): # doctest: +SKIP
        >>>     result = (table['halo_mvir'] > 1e14) & (table['gal_type'] == 'satellites') # doctest: +SKIP
        >>>     return result # doctest: +SKIP
        >>> r, cluster_sat_clustering = model.compute_average_galaxy_clustering(mask_function = my_masking_function) # doctest: +SKIP 

        Notes 
        -----
        The `compute_average_galaxy_clustering` method bound to mock instances is just a convenience wrapper 
        around the `~halotools.mock_observables.clustering.tpcf` function. If you wish for greater 
        control over how your galaxy clustering signal is estimated, 
        see the `~halotools.mock_observables.clustering.tpcf` documentation. 
        """
        if summary_statistic == 'mean':
            summary_func = np.mean 
        else:
            summary_func = np.median

        halocat_kwargs = {}
        if 'simname' in kwargs:
            halocat_kwargs['simname'] = kwargs['simname']
        if 'desired_redshift' in kwargs:
            halocat_kwargs['redshift'] = kwargs['desired_redshift']
        if 'halo_finder' in kwargs:
            halocat_kwargs['halo_finder'] = kwargs['halo_finder']

        halocat = HaloCatalog(preload_halo_table = True, **halocat_kwargs)

        if 'rbins' in kwargs:
            rbins = kwargs['rbins']
        else:
            rbins = model_defaults.default_rbins

        if 'include_crosscorr' in kwargs.keys():
            include_crosscorr = kwargs['include_crosscorr']
        else:
            include_crosscorr = False

        if include_crosscorr is True:

            xi_coll = np.zeros(
                (len(rbins)-1)*num_iterations*3).reshape(3, num_iterations, len(rbins)-1)

            for i in range(num_iterations):
                self.populate_mock(halocat = halocat)
                rbin_centers, xi_coll[0, i, :], xi_coll[1, i, :], xi_coll[2, i, :] = (
                    self.mock.compute_galaxy_clustering(**kwargs)
                    )
            xi_11 = summary_func(xi_coll[0, :], axis=0)
            xi_12 = summary_func(xi_coll[1, :], axis=0)
            xi_22 = summary_func(xi_coll[2, :], axis=0)
            return rbin_centers, xi_11, xi_12, xi_22
        else:

            xi_coll = np.zeros(
                (len(rbins)-1)*num_iterations).reshape(num_iterations, len(rbins)-1)

            for i in range(num_iterations):
                self.populate_mock(halocat = halocat)
                rbin_centers, xi_coll[i, :] = self.mock.compute_galaxy_clustering(**kwargs)
            xi = summary_func(xi_coll, axis=0)
            return rbin_centers, xi

    def compute_average_galaxy_matter_cross_clustering(self, num_iterations=5, 
        summary_statistic = 'median', **kwargs):
        """
        Method repeatedly populates a simulation with a mock galaxy catalog, 
        computes the galaxy-matter cross-correlation  
        signal of each Monte Carlo realization, and returns a summary statistic of the clustering 
        such as the median computed from the collection of repeated measurements. 

        Parameters 
        ----------
        num_iterations : int, optional 
            Number of Monte Carlo realizations to use to estimate the clustering signal. 
            Default is 5.

        summary_statistic : string, optional 
            String specifying the method used to estimate the clustering signal from the 
            collection of Monte Carlo realizations. Options are ``median`` and ``mean``. 
            Default is ``median``. 

        simname : string, optional 
            Nickname of the simulation into which mock galaxies will be populated. 
            Currently supported simulations are 
            Bolshoi  (simname = ``bolshoi``), Consuelo (simname = ``consuelo``), 
            MultiDark (simname = ``multidark``), and Bolshoi-Planck (simname = ``bolplanck``). 
            Default is set in `~halotools.sim_manager.sim_defaults`. 

        halo_finder : string, optional  
            Nickname of the halo-finder of the halocat into which mock galaxies 
            will be populated, e.g., `rockstar` or `bdm`. 
            Default is set in `~halotools.sim_manager.sim_defaults`. 

        desired_redshift : float, optional
            Redshift of the desired halocat into which mock galaxies will be populated. 
            Default is set in `~halotools.sim_manager.sim_defaults`. 

        variable_galaxy_mask : scalar, optional 
            Any value used to construct a mask to select a sub-population 
            of mock galaxies. See examples below. 

        mask_function : array, optional 
            Function object returning a masking array when operating on the galaxy_table. 
            More flexible than the simpler ``variable_galaxy_mask`` option because ``mask_function``
            allows for the possibility of multiple simultaneous cuts. See examples below. 

        include_complement : bool, optional 
            Only for simultaneous use with a ``variable_galaxy_mask``-determined mask. 
            If ``include_complement`` is set to False (the default option), method will return 
            the cross-correlation function between a random downsampling of dark matter particles 
            and the subsample of galaxies determined by 
            the input ``variable_galaxy_mask``. If ``include_complement`` is True, 
            method will also return the cross-correlation between the dark matter particles 
            and the complementary subsample. See examples below. 

        rbins : array, optional 
            Bins in which the correlation function will be calculated. 
            Default is set in `~halotools.empirical_models.model_defaults` module. 

        Examples 
        ---------
        The simplest use-case of the `compute_average_galaxy_matter_cross_clustering` function 
        is just to call the function with no arguments. This will generate a sequence 
        of Monte Carlo realizations of your model into the default halocat, 
        calculate the cross-correlation function between dark matter 
        and all galaxies in your mock, and return the median 
        clustering strength in each radial bin: 

        >>> model = Leauthaud11() # doctest: +SKIP 
        >>> r, clustering = model.compute_average_galaxy_matter_cross_clustering() # doctest: +SKIP 

        To control how which simulation is used, you use the same syntax you use to load 
        a `~halotools.sim_manager.HaloCatalog` into memory from your cache directory: 

        >>> r, clustering = model.compute_average_galaxy_matter_cross_clustering(simname = 'multidark', desired_redshift=1) # doctest: +SKIP 

        You can control the number of mock catalogs that are generated via: 

        >>> r, clustering = model.compute_average_galaxy_matter_cross_clustering(num_iterations = 10) # doctest: +SKIP 

        You may wish to focus on the clustering signal for a specific subpopulation. To do this, 
        you have two options. First, you can use the ``variable_galaxy_mask`` mechanism: 

        >>> r, clustering = model.compute_average_galaxy_matter_cross_clustering(gal_type = 'centrals') # doctest: +SKIP 

        With the ``variable_galaxy_mask`` mechanism, you are free to use any column of your galaxy_table 
        as a keyword argument. If you couple this function call with the ``include_complement`` 
        keyword argument, the function will also return the correlation function of the complementary subset. 

        >>> r, cen_clustering, sat_clustering = model.compute_average_galaxy_matter_cross_clustering(gal_type = 'centrals', include_complement = True) # doctest: +SKIP 

        Your second option is to use the ``mask_function`` option. 
        For example, suppose we wish to study the galaxy-matter cross-correlation function of satellite galaxies 
        residing in cluster-mass halos:

        >>> def my_masking_function(table): # doctest: +SKIP
        >>>     result = (table['halo_mvir'] > 1e14) & (table['gal_type'] == 'satellites') # doctest: +SKIP
        >>>     return result # doctest: +SKIP
        >>> r, cluster_sat_clustering = model.compute_average_galaxy_matter_cross_clustering(mask_function = my_masking_function) # doctest: +SKIP 

        Returns 
        --------
        rbin_centers : array 
            Midpoint of the bins used in the correlation function calculation 

        correlation_func : array 
            If not using any mask (the default option), method returns the 
            correlation function of the full mock galaxy catalog. 

            If using a mask, and if ``include_crosscorr`` is False (the default option), 
            method returns the correlation function of the subsample of galaxies determined by 
            the input mask. 

            If using a mask, and if ``include_crosscorr`` is True, 
            method will return the auto-correlation of the subsample, 
            the cross-correlation of the subsample and the complementary subsample, 
            and the the auto-correlation of the complementary subsample, in that order. 
            See the example below. 

        Notes 
        -----
        The `compute_average_galaxy_matter_cross_clustering` method bound to 
        mock instances is just a convenience wrapper 
        around the `~halotools.mock_observables.clustering.tpcf` function. If you wish for greater 
        control over how your galaxy clustering signal is estimated, 
        see the `~halotools.mock_observables.clustering.tpcf` documentation. 
        """
        if summary_statistic == 'mean':
            summary_func = np.mean 
        else:
            summary_func = np.median

        halocat_kwargs = {}
        if 'simname' in kwargs:
            halocat_kwargs['simname'] = kwargs['simname']
        if 'desired_redshift' in kwargs:
            halocat_kwargs['redshift'] = kwargs['desired_redshift']
        if 'halo_finder' in kwargs:
            halocat_kwargs['halo_finder'] = kwargs['halo_finder']

        halocat = HaloCatalog(preload_halo_table = True, **halocat_kwargs)

        if 'rbins' in kwargs:
            rbins = kwargs['rbins']
        else:
            rbins = model_defaults.default_rbins

        if 'include_complement' in kwargs.keys():
            include_complement = kwargs['include_complement']
        else:
            include_complement = False

        if include_complement is True:

            xi_coll = np.zeros(
                (len(rbins)-1)*num_iterations*2).reshape(2, num_iterations, len(rbins)-1)

            for i in range(num_iterations):
                self.populate_mock(halocat = halocat)
                rbin_centers, xi_coll[0, i, :], xi_coll[1, i, :] = (
                    self.mock.compute_galaxy_matter_cross_clustering(**kwargs)
                    )
            xi_11 = summary_func(xi_coll[0, :], axis=0)
            xi_22 = summary_func(xi_coll[1, :], axis=0)
            return rbin_centers, xi_11, xi_22
        else:

            xi_coll = np.zeros(
                (len(rbins)-1)*num_iterations).reshape(num_iterations, len(rbins)-1)

            for i in range(num_iterations):
                self.populate_mock(halocat = halocat)
                rbin_centers, xi_coll[i, :] = self.mock.compute_galaxy_matter_cross_clustering(**kwargs)
            xi = summary_func(xi_coll, axis=0)
            return rbin_centers, xi







class HodModelArchitect(object):
    """ Class used to create customized HOD-style models.  
    """

    def __init__(self):
        pass

    @staticmethod
    def customize_model(*args, **kwargs):
        """ Method takes a baseline composite model as input, 
        together with an arbitrary number of new component models, 
        and swaps in the new component models to create a and return new composite model. 

        Parameters 
        ----------
        baseline_model : HOD model instance 
            `~halotools.empirical_models.HodModelFactory` instance. 

        component_models : Halotools objects 
            Instance of any component model that you want to swap in to the baseline_model. 

        Returns 
        --------
        new_model : HOD model instance  
            `~halotools.empirical_models.HodModelFactory` instance. The ``new_model`` will 
            be identical in every way to the ``baseline_model``, except the features in the 
            input component_models will replace the features in the ``baseline_model``. 

        """

        try:
            baseline_model = kwargs['baseline_model']
        except KeyError:
            msg = ("\nThe customize_model method of HodModelArchitect "
                "requires a baseline_model keyword argument\n")
            raise HalotoolsError(msg)
        baseline_dictionary = baseline_model.model_dictionary
        new_dictionary = copy(baseline_dictionary)

        for new_component in args:
            try:
                gal_type = new_component.gal_type
                galprop_name = new_component.galprop_name
            except AttributeError:
                msg = ("\nEvery argument of the customize_model method of HodModelArchitect "
                    "must be a model instance that has a ``gal_type`` and a ``galprop_name`` attribute.\n")
                raise HalotoolsError(msg)

            # Enforce self-consistency in the thresholds of new and old components
            if galprop_name == 'occupation':
                old_component = baseline_dictionary[gal_type][galprop_name]
                if new_component.threshold != old_component.threshold:
                    msg = ("\n\nYou tried to swap in a %s occupation component \nthat has a different " 
                        "threshold than the original %s occupation component.\n"
                        "This is technically permissible, but in general, composite HOD-style models \n"
                        "must have the same threshold for all occupation components.\n"
                        "Thus if you do not request the HodModelArchitect to make the corresponding threshold change \n"
                        "for all gal_types, the resulting composite model will raise an exception and not build.\n")
                    warn(msg % (gal_type, gal_type)) 

            new_dictionary[gal_type][galprop_name] = new_component

        new_model = HodModelFactory(new_dictionary)
        return new_model






















