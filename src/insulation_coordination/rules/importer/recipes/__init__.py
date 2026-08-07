"""Declarative recipes for the supported IEC editions."""

from insulation_coordination.rules.importer.recipes.iec60664_1_2020 import (
    RECIPE as IEC60664_1_2020,
)
from insulation_coordination.rules.importer.recipes.iec60664_4_2005 import (
    RECIPE as IEC60664_4_2005,
)
from insulation_coordination.rules.importer.recipes.iec62477_1_2022 import (
    RECIPE as IEC62477_1_2022,
)

RECIPES = (IEC60664_1_2020, IEC60664_4_2005, IEC62477_1_2022)

__all__ = ["RECIPES"]
