"""Plugin registry for connectors and transforms.

Dynamically loads classes and transform functions from the SOURCE_REGISTRY configuration.
"""
from __future__ import annotations

import importlib
import logging
from collections.abc import Callable

from pipeline.config import get_source_config, list_source_ids
from pipeline.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

class SourceRegistry:
    """Dynamic registry of all data source connectors and transforms."""

    def __init__(self) -> None:
        self._connector_cache: dict[str, type[BaseConnector]] = {}
        self._transform_cache: dict[str, Callable] = {}

    def get_connector(self, source_id: str) -> BaseConnector:
        """Return an instantiated connector for the given source_id."""
        if source_id not in self._connector_cache:
            config = get_source_config(source_id)
            cls = self._load_class(config["connector"])
            self._connector_cache[source_id] = cls
            logger.debug("Loaded connector for '%s': %s", source_id, config["connector"])
            
        config = get_source_config(source_id)
        # Pass config to the connector if it accepts it
        try:
            return self._connector_cache[source_id](config=config)
        except TypeError:
            # Fallback for older connectors that don't take config
            return self._connector_cache[source_id]()

    def get_transform(self, source_id: str) -> Callable:
        """Return the transform() function for the given source_id."""
        if source_id not in self._transform_cache:
            config = get_source_config(source_id)
            fn = self._load_function(config["transform"])
            self._transform_cache[source_id] = fn
            logger.debug("Loaded transform for '%s': %s", source_id, config["transform"])
        return self._transform_cache[source_id]

    def get_source(self, source_id: str) -> dict:
        return get_source_config(source_id)

    def list_sources(self) -> list[str]:
        return list_source_ids()

    def validate_all(self) -> dict[str, list[str]]:
        """Validate that all registered connectors and transforms can be imported."""
        errors: dict[str, list[str]] = {}
        source_ids = list_source_ids()
        
        for source_id in source_ids:
            source = get_source_config(source_id)
            source_errors: list[str] = []

            try:
                cls = self._load_class(source["connector"])
                if not issubclass(cls, BaseConnector):
                    source_errors.append(f"Connector {source['connector']} does not subclass BaseConnector")
            except Exception as exc:
                source_errors.append(f"Cannot import connector {source['connector']}: {exc}")

            try:
                fn = self._load_function(source["transform"])
                if not callable(fn):
                    source_errors.append(f"Transform {source['transform']} is not callable")
            except Exception as exc:
                source_errors.append(f"Cannot import transform {source['transform']}: {exc}")

            for field in ("source_id", "connector", "transform", "domain", "schedule", "indicators"):
                if field not in source:
                    source_errors.append(f"Missing required field: '{field}'")

            if source_errors:
                errors[source_id] = source_errors
                for err in source_errors:
                    logger.error("Registry validation [%s]: %s", source_id, err)
            else:
                logger.info("Registry validation [%s]: OK", source_id)

        return errors

    @staticmethod
    def _load_class(dotted_path: str) -> type:
        module_path, class_name = dotted_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        return getattr(module, class_name)

    @staticmethod
    def _load_function(dotted_path: str) -> Callable:
        module_path, fn_name = dotted_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        return getattr(module, fn_name)

source_registry = SourceRegistry()
