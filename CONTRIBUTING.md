# Contributing to DupeFinder

Thank you for considering contributing to DupeFinder! This document provides guidelines and instructions for contributing.

## Development Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/Zedidence/DupeFinderGUI.git
   cd DupeFinderGUI
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install in development mode**
   ```bash
   pip install -e ".[dev,progress]"
   ```

4. **Run tests**
   ```bash
   pytest
   ```

## Code Style

We use the following tools to maintain code quality:

- **Black** for code formatting (line length: 100)
- **Ruff** for linting
- **MyPy** for type checking (optional, best effort)

Run formatting and linting:
```bash
# Format code
black dupefinder/ tests/

# Check imports
isort dupefinder/ tests/

# Lint
ruff check dupefinder/ tests/

# Type check
mypy dupefinder/ --ignore-missing-imports
```

## Testing

- Write tests for new features
- Ensure all tests pass before submitting PR
- Aim for >80% code coverage for new code
- Use pytest fixtures from `tests/conftest.py`

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=dupefinder --cov-report=html

# Run specific test file
pytest tests/test_scanner.py
```

## Pull Request Process

1. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes**
   - Write clean, documented code
   - Add tests for new functionality
   - Update documentation (README, docstrings)

3. **Commit your changes**
   ```bash
   git add .
   git commit -m "Add feature: brief description"
   ```

4. **Push and create PR**
   ```bash
   git push origin feature/your-feature-name
   ```
   Then open a Pull Request on GitHub

5. **PR Requirements**
   - All tests pass
   - Code is formatted with Black
   - No linting errors from Ruff
   - Includes tests for new features
   - Documentation updated
   - Clear description of changes

## Reporting Bugs

When reporting bugs, please include:

- **OS and Python version**
- **DupeFinder version**: `python -m dupefinder --version`
- **Steps to reproduce** the issue
- **Expected behavior**
- **Actual behavior**
- **Error messages** (full traceback if applicable)
- **Sample data** if relevant (small test images)

## Feature Requests

We welcome feature requests! Please:

1. Check existing issues first to avoid duplicates
2. Clearly describe the feature and its use case
3. Explain why it would be valuable
4. Consider if you'd be willing to implement it yourself

## Code of Conduct

- Be respectful and inclusive
- Welcome newcomers and help them get started
- Focus on constructive feedback
- Assume good intentions

## Questions?

Feel free to:
- Open an issue for questions
- Check existing issues and discussions
- Review the README and documentation

Thank you for contributing to DupeFinder!
