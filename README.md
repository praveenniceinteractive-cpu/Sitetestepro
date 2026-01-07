# SiteTesterPro

A comprehensive website auditing platform built with FastAPI, Playwright, and Supabase.

## Features

- **Static Audits**: Capture screenshots across multiple browsers and resolutions
- **Dynamic Audits**: Record full-page scrolling videos
- **H1 Tag Audits**: Analyze SEO-critical heading tags
- **Phone Number Audits**: Validate phone numbers across different formats
- **User Authentication**: Secure auth powered by Supabase
- **Session Management**: Track and manage audit history

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL database (or Supabase account)
- Node.js (for Playwright browsers)

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd 05-01-2026-1
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   playwright install  # Install browser binaries
   ```

4. **Configure environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

5. **Run the application**
   ```bash
   uvicorn main:app --reload
   ```

6. **Access the application**
   - Open http://localhost:8000
   - Register a new account
   - Start your first audit!

## Environment Variables

See `.env.example` for all required configuration. Key variables:

- `DATABASE_URL`: PostgreSQL connection string
- `SUPABASE_URL`: Your Supabase project URL
- `SUPABASE_KEY`: Supabase anon/public key
- `SECRET_KEY`: JWT signing key (generate with `openssl rand -hex 32`)

## Running Tests

```bash
pytest tests/ -v --cov=.
```

## Project Structure

```
├── main.py              # FastAPI application and routes
├── auth.py              # Supabase authentication logic
├── models.py            # SQLAlchemy database models
├── database.py          # Database configuration
├── config.py            # Centralized settings
├── requirements.txt     # Python dependencies
├── static/              # CSS and JavaScript files
├── templates/           # Jinja2 HTML templates
└── tests/               # Test suite
```

## Security Notes

- Never commit `.env` file to version control
- Rotate `SECRET_KEY` in production
- Use strong passwords for database and Supabase
- Enable SSL for PostgreSQL connections in production

## Performance Tips

- Database uses connection pooling (10 connections, 20 max overflow)
- Playwright runs with 5 concurrent browsers max
- Screenshots optimized to WebP format
- Indexes on frequently queried columns

## Troubleshooting

**Issue**: `playwright install` fails
- **Solution**: Run `playwright install-deps` first (Linux)

**Issue**: Database connection errors
- **Solution**: Check `DATABASE_URL` format and network connectivity

**Issue**: Supabase authentication fails
- **Solution**: Verify `SUPABASE_URL` and `SUPABASE_KEY` are correct

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests: `pytest tests/`
5. Submit a pull request

## License

MIT License - see LICENSE file for details

## Support

For issues and questions, please open a GitHub issue or contact support.
