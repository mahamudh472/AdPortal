from rest_framework.exceptions import ValidationError
from main.models import Organization


class RequiredOrganizationIDMixin:
	required_url_kwargs = "org_id"

	def get_org_id(self):
		org_id = self.request.query_params.get(self.required_url_kwargs)
		if not org_id:
			raise ValidationError({
				self.required_url_kwargs: "The parameter is required"
			})
		if not Organization.objects.filter(snowflake_id=org_id).exists():
			raise ValidationError({
				self.required_url_kwargs: "Organization not found"
			})
		return org_id