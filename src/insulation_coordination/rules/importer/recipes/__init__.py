"""Declarative recipes for the supported IEC editions."""

from insulation_coordination.rules.importer.recipes.iec60664_1_2020 import (
    RECIPE as IEC60664_1_2020,
)
from insulation_coordination.rules.importer.recipes.iec60664_4_2005 import (
    RECIPE as IEC60664_4_2005,
)

RECIPES = (IEC60664_1_2020, IEC60664_4_2005)

__all__ = ["RECIPES"]
