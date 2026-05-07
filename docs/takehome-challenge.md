# Original challenge brief — Kaizntree take-home

> This is the original challenge as received. The product context document `PRODUCT.md` represents decisions and additions made on top of this brief — when they conflict, `PRODUCT.md` wins.

---

## Description

Build an inventory management application usable by Food & Beverage CPG brands.

The application must support:

### Product registration

- Products can be manually added.
- Products can have stock added via purchase orders.
- Supported units: kg/g, L/mL, unit.
- Each product must have at minimum: name, description, SKU/code.

### Stock management

- Stocks can be manually added or via purchase orders.
- Each stock has a unique identifier.

### Sales

- Sales orders record product sales (consume product stock).
- Track quantity sold and selling price per unit.

### Financial information

- Track how much was sold and bought (quantity and monetary values).
- Profit analysis: calculate margins by comparing purchase costs against sales revenue.
- Display total revenue, total costs, and profit per product.

---

## Example scenario

A user purchases 100 units of Product A through a PO at $100 total ($1/unit). They later sell all 100 units at $10/unit, generating $1,000 revenue. The system should display:

- Total purchase cost: $100
- Total sales revenue: $1,000
- Profit: $900
- Profit margin: 900%

---

## Technical requirements

### Backend (Python / Django)

- Django + Django REST Framework
- PostgreSQL
- Database models for: Products, Stock, Purchase Orders, Sales Orders, Users, plus any model needed for the application
- API endpoints for all CRUD operations
- Profit calculations and financial tracking on the backend
- Authentication and authorization (users only access their own data)

### Frontend (TypeScript + React)

- React UI with TanStack Query for data fetching
- Mantine for components
- Tailwind for styling when needed
- Interfaces for: login/auth, product listing & creation, PO creation & management, SO creation & management, financial dashboard with profit analysis (per-item financial info), plus any interface needed
- All data fetched from / sent to the Django API

### Authentication

- Simple login system; users only see their own data
- Users only see products, POs, SOs they created
- Proper auth on both frontend and backend

### Optional but desirable

- pytest tests for core modules — focus on business logic (profit calculations), API endpoints, model validations
- Cloud deployment + Docker

### Documentation

- README with overview and setup
- Architectural / technical decisions documented
- API endpoint documentation
- Diagrams welcome

---

## Evaluation criteria

| Criterion | What it means |
|---|---|
| Functionality | Does it meet all business requirements? |
| Code quality | Clean, maintainable, well-organized |
| API design | RESTful principles, proper structure |
| Frontend implementation | Effective use of React, TanStack Query, Mantine |
| Security | Proper auth and data isolation between users |
| Documentation | Clear explanation of decisions and how to run the project |
| Architecture | Well-reasoned technical / architectural choices |
| UI | Clean UI is appreciated |

---

## Timeline

One week from receipt. Coding speed and quality both valued — encouraged to submit ASAP.

---

## Submission

Share via GitHub. Include all documentation in the repository. Send the link when ready.

---

## General notes from Kaizntree

- AI usage cannot be monitored, but candidates must be able to explain technical and architectural decisions in interview.
- Don't focus exclusively on case requirements — propose creative solutions, all base requirements must still be achieved.

---

## References

- Django: https://docs.djangoproject.com/en/5.2/
- DRF: https://www.django-rest-framework.org/
- Classy DRF: https://www.cdrf.co/
- TanStack Query: https://tanstack.com/query/latest
- Mantine: https://mantine.dev/
- pytest: https://docs.pytest.org/en/stable/