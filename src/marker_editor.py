import numpy as num
from PyQt4.QtCore import *  # noqa
from PyQt4.QtGui import *  # noqa

from pyrocko.gui_util import EventMarker, PhaseMarker
from pyrocko import util, orthodrome
from pyrocko.moment_tensor import MomentTensor

_header_data = [
    'T', 'Time', 'Length', 'M', 'Label', 'Depth [km]', 'Lat', 'Lon', 'Dist [km]',
    'Strike', 'Dip', 'Rake']

_column_mapping = dict(zip(_header_data, range(len(_header_data))))


class MarkerItemDelegate(QStyledItemDelegate):
    '''Takes are of the table's style.'''

    def __init__(self, *args, **kwargs):
        QStyledItemDelegate.__init__(self, *args, **kwargs)


class MarkerSortFilterProxyModel(QSortFilterProxyModel):
    '''Sorts the table's columns.'''

    def __init__(self):
        QSortFilterProxyModel.__init__(self)
        self.sort(1, Qt.AscendingOrder)


class MarkerTableView(QTableView):
    def __init__(self, *args, **kwargs):
        QTableView.__init__(self, *args, **kwargs)

        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ContiguousSelection)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.setSortingEnabled(True)
        self.sortByColumn(1, Qt.AscendingOrder)
        self.setAlternatingRowColors(True)

        self.setShowGrid(False)
        self.verticalHeader().hide()
        self.pile_viewer = None

        self.connect(self, SIGNAL('clicked(QModelIndex)'), self.clicked)
        self.connect(
            self, SIGNAL('doubleClicked(QModelIndex)'), self.double_clicked)

        self.header_menu = QMenu(self)

        show_initially = ['Type', 'Time', 'Magnitude']
        self.menu_labels = ['Type', 'Time', 'Length', 'Magnitude', 'Label', 'Depth [km]',
            'Latitude/Longitude', 'Distance [km]', 'Strike/Dip/Rake']
        self.menu_items = dict(zip(self.menu_labels, [0, 1, 2, 3, 4, 5, 6, 8, 9]))
        self.editable_columns = [3, 4, 5, 6, 7 ]

        self.column_actions = {}
        for hd in self.menu_labels:
            a = QAction(QString(hd), self.header_menu)
            self.connect(a, SIGNAL('triggered(bool)'), self.toggle_columns)
            a.setCheckable(True)
            if hd in show_initially:
                a.setChecked(True)
            else:
                a.setChecked(False)
            self.header_menu.addAction(a)
            self.column_actions[hd] = a

        header = self.horizontalHeader()
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        self.connect(header, SIGNAL('customContextMenuRequested(QPoint)'),
                     self.show_context_menu)

    def set_viewer(self, viewer):
        '''Set a pile_viewer and connect to signals.'''

        self.pile_viewer = viewer

    def keyPressEvent(self, key_event):
        self.pile_viewer.keyPressEvent(key_event)

    def clicked(self, model_index):
        '''Ignore mouse clicks.'''

        pass

    def double_clicked(self, model_index):
        if model_index.column() in self.editable_columns:
            return
        else:
            self.emit(SIGNAL('wantDetailView()'))
            self.pile_viewer.go_to_selection()

    def show_context_menu(self, point):
        '''Pop-up menu to toggle columns in the :py:class:`MarkerTableView`.'''

        self.header_menu.popup(self.mapToGlobal(point))

    def toggle_columns(self):
        for header, ca in self.column_actions.items():
            hide = not ca.isChecked()
            if header == 'Latitude/Longitude':
                self.setColumnHidden(self.menu_items[header], hide)
                self.setColumnHidden(self.menu_items[header]+1, hide)
            elif header == 'Strike/Dip/Rake':
                self.setColumnHidden(self.menu_items[header], hide)
                self.setColumnHidden(self.menu_items[header]+1, hide)
                self.setColumnHidden(self.menu_items[header]+2, hide)
            else:
                self.setColumnHidden(self.menu_items[header], hide)
                if header == 'Dist [km]':
                    self.model().update_distances()


class MarkerTableModel(QAbstractTableModel):
    def __init__(self, *args, **kwargs):
        QAbstractTableModel.__init__(self, *args, **kwargs)
        self.pile_viewer = None
        self.headerdata = _header_data
        self.distances = {}
        self.last_active_event = None
        self.row_count = 0

    def set_viewer(self, viewer):
        '''Set a pile_viewer and connect to signals.'''

        self.pile_viewer = viewer
        self.connect(self.pile_viewer,
                     SIGNAL('markers_added(int,int)'),
                     self.markers_added)

        self.connect(self.pile_viewer,
                     SIGNAL('markers_removed(int, int)'),
                     self.markers_removed)

        self.connect(self.pile_viewer,
                     SIGNAL('changed_marker_selection'),
                     self.update_distances)

    def rowCount(self, parent):
        if not self.pile_viewer:
            return 0
        return len(self.pile_viewer.get_markers())

    def columnCount(self, parent):
        return len(_column_mapping)

    def markers_added(self, istart, istop):
        '''Insert rows into table.'''

        self.beginInsertRows(QModelIndex(), istart, istop)
        self.endInsertRows()

    def markers_removed(self, i_from, i_to):
        '''Remove rows from table.'''

        self.beginRemoveRows(QModelIndex(), i_from, i_to)
        self.endRemoveRows()
        self.marker_table_view.updateGeometries()

    def headerData(self, col, orientation, role):
        '''Set and format header data.'''

        if orientation == Qt.Horizontal:
            if role == Qt.DisplayRole:
                return QVariant(self.headerdata[col])
            elif role == Qt.SizeHintRole:
                return QSize(10, 20)
        else:
            return QVariant()

    def data(self, index, role):
        '''Set data in each of the table's cell.'''
        if not self.pile_viewer:
            return QVariant()

        if role == Qt.DisplayRole:
            imarker = index.row()
            marker = self.pile_viewer.markers[imarker]
            s = ' '
            if isinstance(marker, EventMarker):
                marker_type = 'Event'
            elif isinstance(marker, PhaseMarker):
                marker_type = 'Phase'
            else:
                marker_type = ' '

            if index.column() == _column_mapping['T']:
                s = marker_type[0]

            if index.column() == _column_mapping['Time']:
                s = util.time_to_str(marker.tmin)
            if marker_type == 'Event':
                e = marker.get_event()
                if e:
                    mt = e.moment_tensor
                else:
                    mt = None

                if index.column() == _column_mapping['M']:
                    if e:
                        if mt is not None:
                            s = '%2.1f' % (mt.magnitude)
                        elif e.magnitude is not None:
                            s = '%2.1f' % (e.magnitude)

                if index.column() == _column_mapping['Depth [km]']:
                    d = e.depth
                    if d is not None:
                        s = '{0:4.1f}'.format(e.depth/1000.)

                elif index.column() == _column_mapping['Lat']:
                        s = '{0:4.2f}'.format(e.lat)

                elif index.column() == _column_mapping['Lon']:
                        s = '{0:4.2f}'.format(e.lon)

                elif index.column() == _column_mapping['Strike'] and mt is not None:
                        s = '{0:4.2f}'.format(mt.strike1)

                elif index.column() == _column_mapping['Dip'] and mt is not None:
                        s = '{0:4.2f}'.format(mt.dip1)

                elif index.column() == _column_mapping['Rake'] and mt is not None:
                        s = '{0:4.2f}'.format(mt.rake1)

                elif index.column() == _column_mapping['Dist [km]'] and marker in self.distances.keys():
                        s = '{0:6.1f}'.format(self.distances[marker])

            else:
                if index.column() == _column_mapping['Length']:
                    s = '{0:4.2f}'.format(marker.tmax - marker.tmin)
                
            if index.column() == _column_mapping['Label']:
                s = str(marker.get_label())

            return QVariant(QString(s))

        return QVariant()

    def update_distances(self, indices):
        '''Calculate and update distances between events.'''
        if len(indices) != 1 or self.marker_table_view.horizontalHeader()\
                .isSectionHidden(_column_mapping['Dist [km]']):
            return

        if self.last_active_event == self.pile_viewer.get_active_event():
            return
        else:
            self.last_active_event = self.pile_viewer.get_active_event()

        index = indices[0]
        markers = self.pile_viewer.markers
        omarker = markers[index]
        if not isinstance(omarker, EventMarker):
            return

        emarkers = [m for m in markers if isinstance(m, EventMarker)]
        if len(emarkers) < 2:
            return

        lats = num.zeros(len(emarkers))
        lons = num.zeros(len(emarkers))
        for i in xrange(len(emarkers)):
            lats[i] = emarkers[i].get_event().lat
            lons[i] = emarkers[i].get_event().lon

        olats = num.zeros(len(emarkers))
        olons = num.zeros(len(emarkers))
        olats[:] = omarker.get_event().lat
        olons[:] = omarker.get_event().lon
        dists = orthodrome.distance_accurate50m_numpy(lats, lons, olats, olons)
        dists /= 1000.
        self.distances = dict(zip(emarkers, dists))
        self.done()

        # expensive!
        self.reset()

    def done(self):
        self.emit(SIGNAL('dataChanged()'))
        return True

    def setData(self, index, value, role):
        '''Manipulate :py:class:`EventMarker` instances.'''

        if role == Qt.EditRole:
            imarker = index.row()
            marker = self.pile_viewer.markers[imarker]
            e = marker.get_event()
            if index.column() == _column_mapping['Label']:
                values = str(value.toString())
                if values != '':
                    if e:
                        e.set_name(values)
                        return self.done()

                    if isinstance(marker, PhaseMarker):
                        marker.set_phasename(values)
                        return self.done()
            e = marker.get_event()
 
            if not e:
                return False
            mt = e.moment_tensor
            if mt is None:
                mt = MomentTensor()
                e.moment_tensor = mt

            valuef, valid = value.toFloat()
            if index.column() == _column_mapping['M']:
                if valid and e:
                    if not mt:
                        e.magnitude = valuef
                    else:
                        e.moment_tensor.magnitude = valuef
                    return self.done()
            
            elif index.column() == _column_mapping['Lat']:
                e.lat = valuef
            elif index.column() == _column_mapping['Lon']:
                e.lon = valuef
            elif index.column() == _column_mapping[ 'Depth [km]']:
                e.depth = valuef * 1000.
            return self.done()

        return False

    def flags(self, index):
        '''Set flags for cells which the user can edit.'''

        if index.column() not in self.marker_table_view.editable_columns:
            return Qt.ItemFlags(33)
        else:
            if isinstance(self.pile_viewer.markers[index.row()], EventMarker):
                if index.column() in self.marker_table_view.editable_columns:
                    return Qt.ItemFlags(35)
            if index.column() == _column_mapping['Label']:
                return Qt.ItemFlags(35)
        return Qt.ItemFlags(33)


class MarkerEditor(QFrame):
    def __init__(self, *args, **kwargs):
        QFrame.__init__(self, *args, **kwargs)

        #self.layout = QGridLayout()
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.layout)
        self.marker_table = MarkerTableView()
        self.marker_table.setItemDelegate(
            MarkerItemDelegate(self.marker_table))

        self.marker_model = MarkerTableModel()
        self.marker_model.marker_table_view = self.marker_table

        self.proxy_filter = MarkerSortFilterProxyModel()
        self.proxy_filter.setDynamicSortFilter(True)
        self.proxy_filter.setSourceModel(self.marker_model)

        self.marker_table.setModel(self.proxy_filter)

        header = self.marker_table.horizontalHeader()
        header.setDefaultSectionSize(30)
        header.setResizeMode(0, QHeaderView.Interactive)
        header.resizeSection(0, 40)
        for i in xrange(len(_header_data)):
            header.setResizeMode(i+2, QHeaderView.Interactive)
            header.resizeSection(i+2, 70)
        header.setResizeMode(1, QHeaderView.Interactive)
        header.resizeSection(1, 190)
        header.setStretchLastSection(True)

        self.setMinimumWidth(335)

        self.selection_model = QItemSelectionModel(self.proxy_filter)
        self.marker_table.setSelectionModel(self.selection_model)
        self.connect(
            self.selection_model,
            SIGNAL('selectionChanged(QItemSelection, QItemSelection)'),
            self.set_selected_markers)

        self.connect(self.marker_table,
                     SIGNAL('wantDetailView()'),
                     self.show_details)
        self.layout.addWidget(self.marker_table, 0)
        self.details = EventDetailView()

        self.dock_widget = QDockWidget()
        self.dock_widget.setWidget(self.details)
        self.dock_widget.setVisible(False)
        
        self.layout.addWidget(self.dock_widget, 1)
        self.pile_viewer = None

    def show_details(self):
        selected_rows = self.selection_model.selectedRows()
        assert(len(selected_rows) == 1)
        selected_row = selected_rows[0]
        i_marker = self.proxy_filter.mapToSource(selected_row).row()
        marker = self.pile_viewer.get_markers()[i_marker]
        self.details.set_content(marker)
        self.dock_widget.setVisible(True)

    def set_viewer(self, viewer):
        '''Set a pile_viewer and connect to signals.'''

        self.pile_viewer = viewer
        self.marker_model.set_viewer(viewer)
        self.marker_table.set_viewer(viewer)
        self.connect(
            self.pile_viewer,
            SIGNAL('changed_marker_selection'),
            self.update_selection_model)

        self.marker_table.toggle_columns()

    def set_selected_markers(self, selected, deselected):
        ''' set markers selected in viewer at selection in table.'''

        selected_markers = []
        for i in self.selection_model.selectedRows():
            selected_markers.append(
                self.pile_viewer.markers[
                    self.proxy_filter.mapToSource(i).row()])

        self.pile_viewer.set_selected_markers(selected_markers)

    def get_marker_model(self):
        '''Return :py:class:`MarkerTableModel` instance'''

        return self.marker_model

    def update_selection_model(self, indices):
        '''Adopt marker selections done in the pile_viewer in the tableview.

        :param indices: list of indices of selected markers.'''

        self.selection_model.clearSelection()
        selections = QItemSelection()
        num_columns = len(_header_data)
        flag = QItemSelectionModel.SelectionFlags(
            (QItemSelectionModel.Current | QItemSelectionModel.Select))

        for i in indices:
            left = self.proxy_filter.mapFromSource(
                self.marker_model.index(i, 0))

            right = self.proxy_filter.mapFromSource(
                self.marker_model.index(i, num_columns-1))

            row_selection = QItemSelection(left, right)
            row_selection.select(left, right)
            selections.merge(row_selection, flag)

        if len(indices) != 0:
            self.marker_table.setCurrentIndex(
                self.proxy_filter.mapFromSource(
                    self.marker_model.index(indices[0], 0)))
            self.selection_model.setCurrentIndex(
                self.proxy_filter.mapFromSource(
                    self.marker_model.index(indices[0], 0)),
                QItemSelectionModel.SelectCurrent)

        self.selection_model.select(selections, flag)

        if len(indices) != 0:
            self.marker_table.scrollTo(
                self.proxy_filter.mapFromSource(
                    self.marker_model.index(indices[0], 0)))

class EventDetailView(QFrame):
    def __init__(self, *args, **kwargs):
        QFrame.__init__(self, *args, **kwargs)
        layout = QGridLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.header = ['label', 'tmin', 'magnitude', 'depth', 'assigned phases']
        for i, h in enumerate(self.header):
            layout.addWidget(QLabel(), i, 0)
        self.setLayout(layout)
        self.setVisible(False)

    def set_content(self, marker):
        e = marker.get_event()
        mt = e.moment_tensor
        self.layout().itemAt(0).widget().setText(marker.get_label())
        self.layout().itemAt(1).widget().setText('tmin %s' % marker.tmin)
        self.layout().itemAt(2).widget().setText('tmax %s' % marker.tmax)
        return
        #J    mag = mt.magnitude if mt else e.magnitude
        #J    widgets.append(QLabel('magnitude: %s' % mag))
        #J    widgets.append(QLabel('assigned phases: '))

        #J    assigned_phases = [m for m in
        #J                       self.parent().parent().pile_viewer.get_markers()
        #J                       if m.get_event_hash()==e.get_hash()]
        #J    for p in assigned_phases:
        #J        widgets.append(QLabel(str(p)))

        #Jfor i, widget in enumerate(widgets):
        #J    layout().addWidget(widget, i, 0)
