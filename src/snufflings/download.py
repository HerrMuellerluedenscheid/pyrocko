from PyQt4.QtCore import SIGNAL
from pyrocko import pile, trace, util, io, iris_ws, model
from pyrocko.fdsn import ws as fdsn_ws
from pyrocko.gui_util import EventMarker
import sys, os, math, time, urllib2, logging
import numpy as num
from pyrocko.snuffling import Param, Snuffling, Switch, Choice
pjoin = os.path.join

logger = logging.getLogger('pyrocko.snufflings.iris_data')
logger.setLevel(logging.INFO)

class Download(Snuffling):
    '''
    <html>
    <head>
    <style type="text/css">
        body { margin-left:10px };
    </style>
    </head>
    <body>
    <h1 align="center">Query Catalogs for Waveform Data</h1>
    <p>
    By default <b>Use coordinates of selected event as origin</b> is activated.
    If you would like to modify the center of the area to be queried using the
    <b>Origin latitude</b> and <b>Origin langitude</b> sliders, this switch
    needs to be turned off.
    </body>
    '''
    def setup(self):

        self.set_name('Download Waveforms')
        self.add_parameter(Param('Min Radius [deg]', 'minradius', 0., 0., 20.))
        self.add_parameter(Param('Max Radius [deg]', 'maxradius', 5., 0., 20.))
        self.add_parameter(Param('Origin latitude [deg]', 'lat', 0, -90., 90.))
        self.add_parameter(Param('Origin longitude [deg]', 'lon', 0., -180., 180.))
        self.add_parameter(
            Switch('Use coordinates of selected event as origin', 'useevent', True))
        self.add_parameter(Choice('Datecenter', 'datacenter', 'GEOFON', ['GEOFON', 'IRIS']))
        self.add_parameter(Choice('Channels', 'channel_pattern', 'BH?', ['BH?', 'BHZ', 'HH?', '?H?', '*', '??Z']))
        self.add_trigger('Save', self.save)
        self.set_live_update(False)
        self.current_stuff = None

    def panel_visibility_changed(self, bool):
        if bool:
            self._param_controls['lat'].set_enable(not self.useevent)
            self._param_controls['lon'].set_enable(not self.useevent)
            viewer = self.get_viewer()
            viewer.connect(self._param_controls['useevent'],
                           SIGNAL('sw_toggled(PyQt_PyObject, bool)'),
                           self.toggle_origin_sliders)

    def toggle_origin_sliders(self, control, activated):
        self._param_controls['lat'].set_enable(not activated)
        self._param_controls['lon'].set_enable(not activated)

    def call(self):
        '''Main work routine of the snuffling.'''

        self.cleanup()

        view = self.get_viewer()
        pile = self.get_pile()

        tmin, tmax = view.get_time_range()
        if self.useevent:
            markers = view.selected_markers()
            if len(markers) != 1:
                self.fail('Exactly one marker must be selected.')
            marker = markers[0]
            if not isinstance(marker, EventMarker):
                self.fail('An event marker must be selected.')

            ev = marker.get_event()
            lat, lon = ev.lat, ev.lon
        else:
            lat, lon = self.lat, self.lon

        site = self.datacenter.lower()
        try:
            kwargs = {}
            if site == 'iris':
                kwargs['matchtimeseries'] = True

            sx = fdsn_ws.station(site=site, latitude=lat, longitude=lon, minradius=self.minradius, 
                            maxradius=self.maxradius, startbefore=tmin, endafter=tmax,
                            channel=self.channel_pattern, format='text', level='channel',
                            includerestricted=False, **kwargs)

        except fdsn_ws.EmptyResult:
            self.fail('No stations matching given criteria.')

        stations = sx.get_pyrocko_stations()
        networks = set( [ s.network for s in stations ] )

        t2s = util.time_to_str
        dir = self.tempdir()
        fns = []
        for net in networks:
            nstations = [ s for s in stations if s.network == net ]
            selection = fdsn_ws.make_data_selection( nstations, tmin, tmax )
            if selection:
                for x in selection:
                    logger.info('Adding data selection: %s.%s.%s.%s %s - %s' % (tuple(x[:4]) + (t2s(x[4]), t2s(x[5]))))

                try:
                    d = fdsn_ws.dataselect(site=site, selection=selection)
                    fn = pjoin(dir,'data-%s.mseed' % net) 
                    f = open(fn, 'w')
                    f.write(d.read())
                    f.close()
                    fns.append(fn)

                except fdsn_ws.EmptyResult:
                    pass

        all_traces = []
        for fn in fns:
            try:
                traces = list(io.load(fn))

                all_traces.extend(traces)

            except io.FileLoadError, e:
                logger.warning('File load error, %s' % e)
        
        if all_traces:
            newstations = []
            for sta in stations:
                if not view.has_station(sta):
                    logger.info('Adding station: %s.%s.%s' % (sta.network, sta.station, sta.location))
                    newstations.append(sta)
           
            view.add_stations(newstations)
            
            for tr in all_traces:
                logger.info('Adding trace: %s.%s.%s.%s %s - %s' % (tr.nslc_id + (t2s(tr.tmin), t2s(tr.tmax))))
            
            self.add_traces(all_traces)
            self.current_stuff = (all_traces, stations)

        else:
            self.current_stuff = None
            self.fail('Did not get any data for given selection.')
        
    def save(self):
        if not self.current_stuff:
            self.fail('Nothing to save.')
        
        data_fn = self.output_filename(caption='Save Data', dir='data-%(network)s-%(station)s-%(location)s-%(channel)s-%(tmin)s.mseed')
        stations_fn = self.output_filename(caption='Save Stations File', dir='stations.txt')        

        all_traces, stations = self.current_stuff
        io.save(all_traces, data_fn)
        model.dump_stations(stations, stations_fn)

def __snufflings__():    
   return [ Download() ]

