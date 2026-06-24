"""Unit tests for domain schema validators across all three optimization domains."""
from __future__ import annotations

from datetime import time

import pytest
from pydantic import ValidationError

from src.domain.routing_schemas import DeliveryStop, GeoPoint


class TestGeoPoint:
    def test_valid_coordinates(self):
        p = GeoPoint(latitude=40.0, longitude=-74.0)
        assert p.latitude == 40.0

    def test_latitude_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            GeoPoint(latitude=91.0, longitude=0.0)

    def test_longitude_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            GeoPoint(latitude=0.0, longitude=181.0)


class TestDeliveryStop:
    def test_valid_time_window(self):
        stop = DeliveryStop(
            location=GeoPoint(latitude=40.0, longitude=-74.0), demand_units=5,
            time_window_start=time(9, 0), time_window_end=time(17, 0),
        )
        assert stop.time_window_end > stop.time_window_start

    def test_end_before_start_rejected(self):
        with pytest.raises(ValidationError):
            DeliveryStop(
                location=GeoPoint(latitude=40.0, longitude=-74.0), demand_units=5,
                time_window_start=time(17, 0), time_window_end=time(9, 0),
            )

    def test_equal_start_and_end_rejected(self):
        with pytest.raises(ValidationError):
            DeliveryStop(
                location=GeoPoint(latitude=40.0, longitude=-74.0), demand_units=5,
                time_window_start=time(9, 0), time_window_end=time(9, 0),
            )

    def test_demand_must_be_positive(self):
        with pytest.raises(ValidationError):
            DeliveryStop(location=GeoPoint(latitude=40.0, longitude=-74.0), demand_units=0)


class TestSKULocation:
    def test_valid_sku_location(self, sample_sku_location):
        assert sample_sku_location.current_stock >= 0

    def test_negative_stock_rejected(self, sample_sku_location):
        with pytest.raises(ValidationError):
            sample_sku_location.model_copy(update={"current_stock": -1})

    def test_zero_demand_forecast_rejected(self, sample_sku_location):
        with pytest.raises(ValidationError):
            sample_sku_location.model_copy(update={"daily_demand_forecast": 0})


class TestNetworkRequest:
    def test_valid_request(self, sample_network_request):
        assert len(sample_network_request.warehouses) == 2

    def test_negative_lane_cost_rejected(self, sample_network_request):
        bad_lane = sample_network_request.shipping_lanes[0].model_copy(update={"cost_per_unit": -1.0})
        with pytest.raises(ValidationError):
            sample_network_request.model_copy(update={"shipping_lanes": [bad_lane]})
