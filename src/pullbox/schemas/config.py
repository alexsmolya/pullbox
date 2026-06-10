"""Configuration request/response schemas."""

from pydantic import BaseModel, ConfigDict, Field


class ConfigResponse(BaseModel):
    """System configuration key-value pair."""

    model_config = ConfigDict(from_attributes=True)

    key: str = Field(description="Configuration key")
    value: str = Field(description="Configuration value")
    value_type: str = Field(description="Value type (string, int, bool, json)")
    description: str | None = None


class ConfigUpdate(BaseModel):
    """Request body for updating configuration values."""

    values: dict[str, str] = Field(..., min_length=1, description="Key-value pairs to update")


class NamingPreview(BaseModel):
    """Preview of file naming convention applied to sample data."""

    template: str = Field(description="The naming template string")
    examples: list[str] = Field(description="Sample filenames generated from the template")


class NamingPreviewEntry(BaseModel):
    """Single preview example showing input metadata and formatted output."""

    input: str = Field(description="Human-readable description of the source metadata")
    output: str = Field(description="Formatted filename or folder name")


class NamingPreviewGrouped(BaseModel):
    """Grouped preview results for a naming template."""

    template: str = Field(description="The naming template string")
    template_type: str = Field(description="Template type: folder, standard, annual, non_standard")
    examples: list[NamingPreviewEntry] = Field(description="Preview examples")
