# -*- coding: utf-8 -*-
#
#  Project: MXCuBE
#  https://github.com/mxcube.
#
#  This file is part of MXCuBE software.
#
#  MXCuBE is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Lesser General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  MXCuBE is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Lesser General Public License for more details.
#
#  You should have received a copy of the GNU General Lesser Public License
#  along with MXCuBE.  If not, see <http://www.gnu.org/licenses/>.
"""Resolution as motor."""

import logging
from scipy import arcsin, arctan, sin, sqrt, tan
from scipy.constants import h, c, e
from HardwareRepository import HardwareRepository as HWR
from HardwareRepository.HardwareObjects.abstract.AbstractMotor import (
    AbstractMotor,
)

__copyright__ = """ Copyright © 2019 by the MXCuBE collaboration """
__license__ = "LGPLv3+"


class Resolution(AbstractMotor):
    """Resolution as motor"""

    def __init__(self, name):
        AbstractMotor.__init__(self, name=name)

        self.det_width = None
        self.det_height = None
        self.det_radius = None
        self.position = None
        self._hwr_detector = None
        self._hwr_energy = None

    def init(self):
        """Initialise the motor"""
        AbstractMotor.init(self)
        self._hwr_detector = HWR.beamline.detector
        self._hwr_energy = HWR.beamline.energy

        if self._hwr_detector:
            self.det_width = float(self._hwr_detector.getProperty("width"))
            self.det_height = float(self._hwr_detector.getProperty("height"))
        else:
            logging.getLogger().exception("Cannot get detector properties")
            raise AttributeError("Cannot get detector properties")

        self.connect(self._hwr_detector.distance, "stateChanged", self.update_state)
        self.connect(
            self._hwr_detector.distance, "positionChanged", self.update_position
        )
        self.connect(self._hwr_energy, "valueChanged", self.update_energy)

    def is_ready(self):
        """Check if the distance motor state is READY.
        Returns:
            (bool): True if ready, otherwise False.
        """
        try:
            return self._hwr_detector.distance.is_ready()
        except AttributeError:
            return False

    def get_state(self):
        """Get the state of the distance motor.
        Returns:
            (enum 'MotorStates'): Motor state.
        """
        return self._hwr_detector.distance.get_state()

    def get_position(self):
        """Read the position.
        Returns:
            (float): position.
        """
        if self.position is None:
            dtox_pos = self._hwr_detector.distance.get_position()
            self.get_detector_radius(dtox_pos)
            self.position = self.dist2res(dtox_pos)
        return self.position

    def get_limits(self):
        """Return resolution low and high limits.
        Returns:
            (tuple): two floats tuple (low limit, high limit).
        """
        _low, _high = self._hwr_detector.distance.get_limits()

        self._limits = (self.dist2res(_low), self.dist2res(_high))
        return self._limits

    def move(self, position, wait=False, timeout=None):
        """Move resolution to absolute position. Wait the move to finish.
        Args:
            position (float): target position [Å]
            wait (bool): optional - wait until motor movement finished.
            timeout (float): optional - timeout [s].
        """
        logging.getLogger().info(
            "move Resolution to {} ({} mm)".format(position, self.res2dist(position))
        )

        self._hwr_detector.distance.move(
            self.res2dist(position), wait=wait, timeout=timeout
        )

    def _get_wavelength(self):
        """Get or calculate the wavelength.
        Returns:
            (float): wavelength [Å]
        """
        try:
            return self._hwr_energy.get_wavelength()
        except AttributeError:
            _en = self._hwr_energy.get_value()
            if _en:
                # energy in KeV to get wavelength in Å
                _en = _en / 1000.0 if _en > 1000 else _en
                hc_over_e = h * c / e
                return hc_over_e / _en * 10e6
            return None

    def _calculate_resolution(self, radius, distance):
        """Calculate the resolution as function of the detector radius and the distance.
        Args:
            radius (float): Detector radius [mm]
            distance (float): Distance from the sample to the detector [mm]
        Returns:
            (float): Resolution [Å]
        """
        _wavelength = self._get_wavelength()

        try:
            ttheta = arctan(radius / distance)
            if ttheta:
                return _wavelength / (2 * sin(ttheta / 2))
        except (TypeError, ZeroDivisionError):
            logging.getLogger().exception("error while calculating resolution")
        return None

    def dist2res(self, distance=None):
        """Convert distance to resolution.
        Args:
            distance (float): Distance [mm].
        Returns:
            (float): Resolution [Å].
        """
        if distance is None:
            distance = self._hwr_detector.distance.get_position()

        return self._calculate_resolution(self.det_radius, distance)

    def res2dist(self, resolution=None):
        """Convert resolution to distance.
        Args:
            resolution(float): Resolution [Å].
        Returns:
            (float): distance [mm].
        """
        _wavelength = self._get_wavelength()

        if resolution is None:
            resolution = self.position

        ax = float(self._hwr_detector["beam"].getProperty("ax"))
        bx = float(self._hwr_detector["beam"].getProperty("bx"))
        ay = float(self._hwr_detector["beam"].getProperty("ay"))
        by = float(self._hwr_detector["beam"].getProperty("by"))

        try:
            ttheta = 2 * arcsin(_wavelength / (2 * resolution))

            dist_1 = bx / (tan(ttheta) - ax)
            dist_2 = by / (tan(ttheta) - ay)
            dist_3 = (self.det_width - bx) / (tan(ttheta) + ax)
            dist_4 = (self.det_height - by) / (tan(ttheta) + ay)

            return min(dist_1, dist_2, dist_3, dist_4)
        except BaseException:
            return None

    def update_energy(self, energy):
        """Calculate the resolution whe changing the energy.
        Args:
            energy(float): Energy [KeV]
        """
        _wavelength = (h * c / e) / energy * 10e6

        distance = self._hwr_detector.distance.get_position()
        radius = self.get_detector_radius(distance)
        try:
            ttheta = arctan(radius / distance)
            if ttheta:
                self.position = _wavelength / (2 * sin(ttheta / 2))
                self.emit("positionChanged", (self.position,))
                self.emit("valueChanged", (self.position,))
        except (TypeError, ZeroDivisionError):
            logging.getLogger().exception("error while calculating resolution")

    def get_beam_centre(self, distance=None):
        """Calculate the beam centre for a given distance.
        Args:
            distance(float): Distance [mm]
        Returns:
            (tuple): Tuple of floats - beam centre X,Y coordinates
        """
        if distance is None:
            distance = self._hwr_detector.distance.get_position()
        ax = float(self._hwr_detector["beam"].getProperty("ax"))
        bx = float(self._hwr_detector["beam"].getProperty("bx"))
        ay = float(self._hwr_detector["beam"].getProperty("ay"))
        by = float(self._hwr_detector["beam"].getProperty("by"))
        return float(distance * ax + bx), float(distance * ay + by)

    def get_detector_radius(self, distance):
        """Get the detector radius for a given distance.
        Args:
            distance (float): Distance [mm]
        Returns:
            (float): Detector radius [mm]
        """
        beam_x, beam_y = self.get_beam_centre(distance)
        self.det_radius = min(
            self.det_width - beam_x, self.det_height - beam_y, beam_x, beam_y
        )
        return self.det_radius

    def get_value_at_corner(self):
        """Get the resolution at the corners of the detector.
        Returns:
            (float): Resolution [Å]
        """
        dtox_pos = self._hwr_detector.distance.get_position()
        beam_x, beam_y = self.get_beam_centre(dtox_pos)

        distance_at_corners = [
            sqrt(beam_x ** 2 + beam_y ** 2),
            sqrt((self.det_width - beam_x) ** 2 + beam_y ** 2),
            sqrt((beam_x ** 2 + (self.det_height - beam_y) ** 2)),
            sqrt((self.det_width - beam_x) ** 2 + (self.det_height - beam_y) ** 2),
        ]
        return self._calculate_resolution(max(distance_at_corners), dtox_pos)

    def connectNotify(self, signal):
        """Check who needs this"""
        if signal == "stateChanged":
            self.update_state(self._hwr_detector.distance.get_state())

    def update_state(self, state):
        """Emist signal stateChanged. Calculate the resolution if needed.
        Args:
            state (enum 'MotorState'): state
        """
        if not state:
            state = self.get_state()
        self.state = state
        self.emit("stateChanged", (self.state,))

    def update_position(self, position=None):
        """Update the beam centre and the resolutoion.
        Args:
            position (float): position [Å]
        """
        if position is None:
            position = self.get_position()
        self.position = position
        self.get_detector_radius(self.position)
        self.update_resolution(self.dist2res(self.position))

    def update_resolution(self, resolution):
        """Emit positionChanged and valueChanged
        Args:
            resolution (float): the resolution value [Å]
        """
        self.position = resolution
        self.emit("positionChanged", (self.position,))
        self.emit("valueChanged", (self.position,))

    def stop(self):
        """Stop the real motor"""
        self._hwr_detector.distance.stop()
