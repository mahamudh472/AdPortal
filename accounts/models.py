from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.db import models
import uuid
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Email must be provided')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Custom user model without mandatory username"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, max_length=255)
    username = models.CharField(max_length=150, blank=True, null=True)
    first_name = models.CharField(max_length=30, blank=True, null=True)
    last_name = models.CharField(max_length=30, blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)

    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    gender = models.CharField(max_length=20, blank=True, null=True,
                              choices=[('male', 'Male'), ('female', 'Female'), ('other', 'Other')])
    age = models.IntegerField(blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    
    joined_at = models.DateTimeField(auto_now_add=True)
    last_login = models.DateTimeField(blank=True, null=True)
    
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    
    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []  # nothing else required for createsuperuser

    class Meta:
        db_table = 'users'

    def __str__(self):
        return self.email
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()


class OTP(models.Model):
    """OTP for authentication purposes"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='otps')
    code = models.CharField(max_length=6)
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    
    class Meta:
        db_table = 'otps'
        verbose_name = 'OTP'
        verbose_name_plural = 'OTPs'
    
    def __str__(self):
        return f"{self.user.email} - {self.purpose} - {self.code}"
    
    def is_valid(self):
        """Check if OTP is still valid"""
        return not self.is_used and timezone.now() < self.expires_at


