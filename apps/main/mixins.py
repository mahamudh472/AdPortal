from rest_framework.exceptions import ValidationError
from apps.main.models import Organization


class RequiredOrganizationIDMixin:
	required_url_kwargs = "org_id"

	def get_org_id(self):
		org_id = self.request.query_params.get(self.required_url_kwargs)
		if not org_id:
			raise ValidationError({
				self.required_url_kwargs: "The parameter is required"
			})
		from apps.accounts.permissions import get_request_organization
		if get_request_organization(self.request) is None:
			raise ValidationError({
				self.required_url_kwargs: "Organization not found"
			})
		return org_id