# AWS Daily Health Checks

Automated daily health-check reports for client AWS environments (BHFS, FleetCor, VISA, SMBC, ...).

## Structure

```
AWS-Daily-HealthChecks/
├── bootstrap.py          # AWS login, AssumeRole, Session, Region Discovery (shared)
├── requirements.txt
├── README.md
├── assets/                # Shared report template, styling, logos
│   ├── report_template.html
│   ├── styles.css
│   └── logos/
├── BHFS/                  # Per-client runner
│   ├── Jenkinsfile
│   ├── main.py
│   ├── config.py
│   ├── checks/
│   ├── lib/
│   │   ├── ssh.py
│   │   ├── database.py
│   │   ├── linux.py
│   │   └── html_report.py
│   └── output/
├── FleetCor/               # Per-client runner (same layout as BHFS)
├── VISA/
├── SMBC/
└── docs/
```

## Usage

Each client folder (`BHFS/`, `FleetCor/`, ...) contains a self-contained `main.py` entry point
that is triggered by its own `Jenkinsfile`. Shared AWS bootstrapping logic lives in the top-level
`bootstrap.py`, and shared HTML report assets live in `assets/`.

1. Install dependencies: `pip install -r requirements.txt`
2. Configure client-specific settings in `<Client>/config.py`
3. Run a client's checks: `python <Client>/main.py`

## Adding a new client

Copy the `BHFS/` folder layout (`Jenkinsfile`, `main.py`, `config.py`, `checks/`, `lib/`, `output/`)
and implement the client-specific checks and configuration.
