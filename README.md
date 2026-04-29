# web-clip-helper

LLM Agent-oriented web clipping CLI tool.

## Installation

```bash
pip install web-clip-helper
```

## Usage

```bash
# Clip a web page to local markdown
web-clip-helper clip <url>

# List all clipped articles
web-clip-helper list

# Get a specific clip by ID
web-clip-helper get <clip-id>

# Search clips by keyword
web-clip-helper search <query>

# List all tags
web-clip-helper tags

# Refresh clips (re-fetch and update)
web-clip-helper refresh

# Collect feedback for an article
web-clip-helper feedback <clip-id>
```

## Configuration

Set your OpenAI API key via environment variable:

```bash
export OPENAI_API_KEY="sk-..."
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT
