# Copyright (C) 2013 Brockmann Consult GmbH (info@brockmann-consult.de)
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 3 of the License, or (at your option)
# any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
# more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, see http://www.gnu.org/licenses/gpl.html
import functools
import logging
import sys

from opec.NetCDFFacade import NetCDFFacade

class Data(object):

    def __init__(self, model_file_name, ref_file_name=None, max_cache_size=None):
        if ref_file_name is not None:
            self.__reference_file = NetCDFFacade(ref_file_name)
        self.__model_file = NetCDFFacade(model_file_name)
        self.__current_storage = {}
        self.max_cache_size = max_cache_size if max_cache_size is not None else sys.maxsize
        self.cached_list = []
        self.current_memory = 0

    def model_vars(self):
        if not hasattr(self, 'model_variables'):
            self.model_variables = self.__model_file.get_model_variables()
        return self.model_variables

    def close(self):
        self.__model_file.close()
        if self.is_ref_data_split():
            self.__reference_file.close()

    def ref_vars(self):
        if hasattr(self, 'reference_variables'):
            return self.reference_variables
        reference_variables = self.__model_file.get_reference_variables()
        if self.is_ref_data_split():
            reference_variables.extend(self.__reference_file.get_reference_variables())
        self.reference_variables = reference_variables
        return reference_variables

    def has_model_dimension(self, dimension_name):
        return self.__model_file.has_model_dimension(dimension_name)

    def reference_coordinate_variables(self):
        variables = self.__model_file.get_ref_coordinate_variables()
        if self.is_ref_data_split():
            variables.extend(self.__reference_file.get_ref_coordinate_variables())
        return variables

    def model_dim_size(self, dim_name):
        return self.dim_size(self.__model_file, dim_name)

    def ref_dim_size(self, dim_name):
        if self.is_ref_data_split():
            return self.dim_size(self.__reference_file, dim_name)
        return self.dim_size(self.__model_file, dim_name)

    def dim_size(self, ncfile, dim_name):
        return ncfile.get_dim_size(dim_name)

    def __dimension_string(self, ncfile, variable_name):
        return ncfile.get_dimension_string(variable_name)

    def is_ref_data_split(self):
        return hasattr(self, '_Data__reference_file')

    def reference_records_count(self, dimension_profile):
        ref_vars = self.ref_vars()
        if not ref_vars:
            return 0
        if self.is_ref_data_split():
            ncfile = self.__reference_file
        else:
            ncfile = self.__model_file

        dim_size = 0
        for var in ref_vars:
            dimensions = self.__dimension_string(ncfile, var).split(' ')
            dimension_set = {x for x in dimensions}
            if dimension_profile == dimension_set:
                temp = 1
                for dim in dimension_profile:
                    temp *= self.dim_size(ncfile, dim)
                dim_size += temp
        return dim_size

    def get_reference_dimensions(self, variable_name=None):
        if self.is_ref_data_split():
            ncfile = self.__reference_file
        else:
            ncfile = self.__model_file
        return ncfile.get_dimensions(variable_name)

    def get_model_dimensions(self, variable_name=None):
        if not hasattr(self, 'model_dimensions'):
            self.model_dimensions = {}
        if not variable_name in self.model_dimensions:
            self.model_dimensions[variable_name] = self.__model_file.get_dimensions(variable_name)
        return self.model_dimensions[variable_name]

    def read_model(self, variable_name, origin=None):
        return self.__read(self.__model_file, variable_name, origin)

    def read_reference(self, variable_name, origin=None):
        ncfile = self.__reference_file if self.is_ref_data_split() else self.__model_file
        return self.__read(ncfile, variable_name, origin)

    def __read(self, ncfile, variable_name, origin=None):
        if not self.__is_cached(variable_name) and self.max_cache_size <= self.current_memory + self.compute_variable_size(variable_name):
            first_in_cache = self.cached_list.pop(0)
            logging.debug('Deleting variable \'%s\' from cache.' % first_in_cache)
            self.__delattr__(first_in_cache)
            self.current_memory -= self.compute_variable_size(first_in_cache)
        if not self.__is_cached(variable_name):
            logging.debug('Reading variable \'%s\' fully into cache.' % variable_name)
            variable = ncfile.get_variable(variable_name)
            self.__setattr__(variable_name, variable[:])
            self.__current_storage[variable_name] = 'fully_read'
            self.cached_list.append(variable_name)
            self.current_memory += self.compute_variable_size(variable_name)
        if self.__can_return_all(origin, variable_name):
            return self.__getattribute__(variable_name)

        return self.get_data(origin, variable_name)


    def get_data(self, origin, variable_name):
        '''
        Read single pixel from origin
        '''

        return self.__getattribute__(variable_name)[tuple(origin)]


    def __is_cached(self, variable_name):
        return variable_name in self.__current_storage.keys()

    def __can_return_all(self, origin, variable_name):
        return origin is None and self.__current_storage[variable_name] == 'fully_read'

    def __find_model_variable_name(self, possible_names, standard_name):
        for name in possible_names:
            if self.__model_file.get_variable(name) is not None:
                return name
        for var in self.__model_file.get_coordinate_variables():
            if self.__model_file.attribute(var.name, 'standard_name') == standard_name:
                return var.name
        raise ValueError('Unable to find \'%s\'-variable.' % standard_name)

    def find_model_latitude_variable_name(self):
        return self.__find_model_variable_name(['lat', 'latitude'], 'latitude')

    def find_model_longitude_variable_name(self):
        return self.__find_model_variable_name(['lon', 'longitude'], 'longitude')

    def unit(self, variable_name):
        is_not_in_ref_file = not self.is_ref_data_split() or self.is_ref_data_split() and self.__reference_file.get_variable(variable_name) is None
        is_not_in_model_file = self.__model_file.get_variable(variable_name) is None
        if is_not_in_model_file and is_not_in_ref_file:
            raise ValueError('Variable \'%s\' not found.' % variable_name)
        if unit(self.__model_file, variable_name):
            return unit(self.__model_file, variable_name)
        if self.is_ref_data_split() and unit(self.__reference_file, variable_name):
            return unit(self.__reference_file, variable_name)
        return None

    def compute_variable_size(self, variable_name):
        variable = self.__model_file.get_variable(variable_name)
        if variable is None and self.is_ref_data_split():
            variable = self.__reference_file.get_variable(variable_name)
        if variable is None:
            raise ValueError('No variable found with name \'%s\'' % variable_name)
        num_entries = functools.reduce(lambda x, y: x * y, variable.shape)
        byte_size = num_entries * variable.dtype.itemsize
        return byte_size / (1024 * 1024)

def unit(ncfile, variable_name):
    if ncfile.get_variable(variable_name):
        return ncfile.get_variable_attribute(variable_name, 'units')
    return None