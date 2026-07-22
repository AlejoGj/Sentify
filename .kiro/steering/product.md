# Sentify — Product Overview

Sentify is a sentiment analysis and customer feedback platform for businesses that receive high volumes of daily reviews. Corporate users upload CSV files containing customer reviews; the system processes each text with NLP to classify sentiment (positive, neutral, negative), extracts dominant keywords, and presents results in an interactive analytics dashboard with urgency triage.

## Core Capabilities

- CSV bulk upload and validation (up to 10 MB / 50,000 rows)
- Automated NLP sentiment classification with score (−1.0 to 1.0)
- Keyword extraction (TF-IDF based, Spanish language)
- Interactive dashboard with charts, word cloud, and paginated feedback
- Urgency triage panel highlighting extremely negative feedback (score < −0.7)
- Auth with JWT tokens, account lockout after failed attempts
- Modular architecture prepared for AWS cloud migration (Comprehend, Cognito, RDS)

## Primary Language

The platform processes Spanish-language text. UI text and documentation are in Spanish.

## Target Users

Corporate users (empresa) who need to understand customer satisfaction at scale without reading every comment manually.
