# CRQ Simulator

A lightweight Cyber Risk Quantification (CRQ) simulator built as an academic research project and foundation for future work in quantitative cyber risk management.

The project explores the application of Monte Carlo simulation and probabilistic modeling to cyber risk estimation, with a particular focus on supporting the objectives of the EU Digital Operational Resilience Act (DORA), especially Pillar II: ICT Risk Management Framework.

## Objectives

* Explore quantitative approaches to cyber risk measurement.
* Investigate the use of Monte Carlo simulation for uncertainty modeling.
* Evaluate the applicability of probabilistic risk estimation to DORA-driven ICT risk management and cloud operational resilience.
* Serve as a foundation for future MSc thesis research in Cyber Risk Quantification.

## Methodology

The simulator models cyber risk using probability distributions rather than deterministic values.

Users define:

* Annual event frequency
* Loss magnitude

For both frequency and magnitude, the model accepts:

* Minimum value
* Most likely value
* Maximum value

These values are transformed into Beta-PERT probability distributions, which are commonly used in risk analysis and expert elicitation.

Optional simulation parameters include:

* Confidence level (`lambda`) for the Beta-PERT distribution (default: `4`)
* Number of Monte Carlo iterations (default: `10,000`)
* Random seed for reproducible simulations

The simulator then executes a Monte Carlo simulation and generates a statistical characterization of the resulting annual loss distribution.

## Outputs

The generated report includes:

* Mean and median annual loss
* Percentiles and confidence intervals
* Value at Risk (VaR)
* Tail Value at Risk (TVaR)
* Loss Exceedance Curve (LEC)
* Frequency-loss scatter plots
* Distribution visualizations and summary statistics

## Running the Application

### Requirements

* Docker
* Docker Compose

### Start the application

```bash
docker compose up -d
```

The application consists of two services:

* `frontend`
* `backend`

## Future Directions

This project is intended to evolve toward a broader Cyber Risk Quantification platform including:

* FAIR-based risk modeling
* DORA Pillar II control effectiveness evaluation
* Cloud resilience quantification
* Scenario analysis
* SME calibration and expert elicitation
* Information lineage and confidence scoring
* Control investment optimization
* Enterprise risk aggregation
* Sector benchmarking and regulatory reporting support
