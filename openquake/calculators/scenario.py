# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (C) 2014-2017 GEM Foundation
#
# OpenQuake is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# OpenQuake is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with OpenQuake. If not, see <http://www.gnu.org/licenses/>.
import collections
import numpy

from openquake.hazardlib.calc import filters
from openquake.hazardlib.calc.gmf import GmfComputer
from openquake.commonlib import readinput, source, calc
from openquake.calculators import base


@base.calculators.add('scenario')
class ScenarioCalculator(base.HazardCalculator):
    """
    Scenario hazard calculator
    """
    is_stochastic = True

    def pre_execute(self):
        """
        Read the site collection and initialize GmfComputer and seeds
        """
        super(ScenarioCalculator, self).pre_execute()
        oq = self.oqparam
        trunc_level = oq.truncation_level
        correl_model = oq.get_correl_model()
        rup = readinput.get_rupture(oq)
        rup.seed = self.oqparam.random_seed
        self.gsims = readinput.get_gsims(oq)
        maxdist = oq.maximum_distance['default']
        with self.monitor('filtering sites', autoflush=True):
            self.sitecol = filters.filter_sites_by_distance_to_rupture(
                rup, maxdist, self.sitecol)
        if self.sitecol is None:
            raise RuntimeError(
                'All sites were filtered out! maximum_distance=%s km' %
                maxdist)
        # eid, ses, occ, sample
        events = numpy.zeros(oq.number_of_ground_motion_fields,
                             calc.stored_event_dt)
        events['eid'] = numpy.arange(oq.number_of_ground_motion_fields)
        self.datastore['events/grp-00'] = events
        rupture = calc.EBRupture(rup, self.sitecol.sids, events, 0, 0)
        rupture.sidx = 0
        rupture.eidx1 = 0
        rupture.eidx2 = len(events)
        rupser = calc.RuptureSerializer(self.datastore)
        rupser.save([rupture], 0)
        rupser.close()
        self.computer = GmfComputer(
            rupture, self.sitecol, oq.imtls, self.gsims,
            trunc_level, correl_model)
        gsim_lt = readinput.get_gsim_lt(oq)
        cinfo = source.CompositionInfo.fake(gsim_lt)
        self.datastore['csm_info'] = cinfo
        self.rlzs_assoc = cinfo.get_rlzs_assoc()

    def init(self):
        pass

    def execute(self):
        """
        Compute the GMFs and return a dictionary gsim -> array(N, E, I)
        """
        self.gmfa = collections.OrderedDict()
        with self.monitor('computing gmfs', autoflush=True):
            n = self.oqparam.number_of_ground_motion_fields
            for gsim in self.gsims:
                gmfa = self.computer.compute(gsim, n)  # shape (I, N, E)
                self.gmfa[gsim] = gmfa.transpose(1, 2, 0)  # shape (N, E, I)
        return self.gmfa

    def post_execute(self, dummy):
        with self.monitor('saving gmfs', autoflush=True):
            self.datastore['gmf_data/data'] = calc.get_gmv_data(
                self.sitecol.sids, numpy.array(list(self.gmfa.values())))
            self.datastore.set_nbytes('gmf_data')
