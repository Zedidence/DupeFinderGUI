# DupeFinder Test Suite

This directory contains the test suite for the Duplicate Image Finder application.

## Running Tests

### Install Test Dependencies

```bash
# Install package with dev dependencies
pip install -e ".[dev]"

# Or install pytest manually
pip install pytest pytest-cov
```

### Run All Tests

```bash
# From project root
pytest

# Or with coverage
pytest --cov=dupefinder --cov-report=html
```

### Run Specific Test Files

```bash
# Run only model tests
pytest tests/test_models.py

# Run only scanner tests
pytest tests/test_scanner.py

# Run only LSH tests
pytest tests/test_lsh.py

# Run only database tests
pytest tests/test_database.py
```

### Run Specific Test Classes or Functions

```bash
# Run a specific test class
pytest tests/test_models.py::TestImageInfo

# Run a specific test function
pytest tests/test_scanner.py::TestFindImageFiles::test_find_png_files
```

### Additional Options

```bash
# Verbose output
pytest -v

# Stop on first failure
pytest -x

# Show local variables on failure
pytest -l

# Run tests in parallel (requires pytest-xdist)
pytest -n auto
```

## Test Structure

- `conftest.py` - Shared fixtures and test configuration
- `test_models.py` - Tests for ImageInfo and DuplicateGroup classes
- `test_scanner.py` - Tests for image scanning and analysis functions
- `test_lsh.py` - Tests for LSH (Locality-Sensitive Hashing) implementation
- `test_database.py` - Tests for SQLite caching functionality
- `fixtures/` - Test data and sample images (auto-generated)

## Test Coverage

To generate a coverage report:

```bash
pytest --cov=dupefinder --cov-report=html
```

Then open `htmlcov/index.html` in your browser to view the detailed coverage report.

## Writing New Tests

When adding new functionality, please add corresponding tests:

1. Create test functions with descriptive names starting with `test_`
2. Use appropriate fixtures from `conftest.py`
3. Follow the Arrange-Act-Assert pattern
4. Add docstrings explaining what the test validates

Example:

```python
def test_my_new_feature(sample_images):
    """Test that my new feature works correctly."""
    # Arrange
    input_data = sample_images['unique']

    # Act
    result = my_new_function(input_data)

    # Assert
    assert result is not None
    assert result.some_property == expected_value
```

## Continuous Integration

Tests are automatically run on:
- Every push to main branch
- Every pull request
- Nightly builds (if configured)

Make sure all tests pass before submitting a pull request.
