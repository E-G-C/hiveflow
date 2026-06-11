# Enterprise Cloud Migration Strategy Assessment

## Objective

Produce a comprehensive assessment report evaluating the migration of a
mid-size enterprise (500 employees, ~40 internal applications) from
on-premises infrastructure to a hybrid cloud architecture.

The report should cover technical feasibility, cost analysis, risk
assessment, and a phased migration roadmap. Target audience is the CTO
and VP of Engineering.

## Constraints

- Focus on Azure and AWS as the two candidate cloud providers
- Assume a 12-month migration timeline
- Budget ceiling of $2M for the migration project
- The company has 3 legacy .NET Framework applications that cannot be
  easily containerized
- Compliance requirements: SOC 2 Type II, GDPR (EU customers)

## Context

The company currently runs:
- 15 microservices on Kubernetes (on-prem)
- 8 monolithic .NET Framework apps on Windows Server 2019
- 12 Python/FastAPI services
- 5 data pipelines on Apache Spark (on-prem Hadoop cluster)
- PostgreSQL and SQL Server databases (~4TB combined)
- On-prem Active Directory with Azure AD Connect already configured

Key pain points:
- Hardware refresh cycle due in 6 months ($800K estimated)
- Scaling bottlenecks during quarterly reporting periods
- Disaster recovery currently limited to tape backups with 24hr RPO

## Deliverable Format

A structured report with:
1. Executive summary (1 page)
2. Current state assessment
3. Cloud provider comparison (Azure vs AWS for this workload)
4. Migration strategy and phased roadmap
5. Risk register with mitigation strategies
6. Cost-benefit analysis with 3-year TCO projection
7. Recommendations and next steps
