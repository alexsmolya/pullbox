"""Route-contract tests for the shared form field helper."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-form-field-ui")


class TestFormFieldRender:
    """Verify the generic form-field select helper uses the shared dropdown contract."""

    @pytest.mark.asyncio
    async def test_select_field_uses_shared_dropdown_contract(self) -> None:
        from pullbox.ui.routes import templates

        template = templates.env.from_string(
            '{% from "components/form_field.html" import form_field %}'
            '{{ form_field("format", "Preferred Format", type="select", value="cbz", '
            'placeholder="Choose a format", '
            'options=[("cbz", "CBZ"), ("pdf", "PDF")]) }}'
        )
        html = template.render(request=MagicMock(), user=MagicMock())

        assert 'data-dropdown-select-contract="v1"' in html
        assert 'data-dropdown-select-mode="form"' in html
        assert '<select id="format"' not in html
        assert 'name="format"' in html
        assert 'id="format"' in html
        assert ">CBZ</span>" in html

    @pytest.mark.asyncio
    async def test_select_field_preserves_error_accessibility(self) -> None:
        from pullbox.ui.routes import templates

        template = templates.env.from_string(
            '{% from "components/form_field.html" import form_field %}'
            '{{ form_field("format", "Preferred Format", type="select", value="", '
            'error="This field is required.", placeholder="Choose a format", '
            'options=[("cbz", "CBZ"), ("pdf", "PDF")]) }}'
        )
        html = template.render(request=MagicMock(), user=MagicMock())

        assert 'aria-invalid="true"' in html
        assert 'aria-describedby="format-error"' in html
        assert 'id="format-error"' in html
        assert "This field is required." in html
