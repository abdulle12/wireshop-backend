from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

User = get_user_model()

class SignupSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])

    class Meta:
        model  = User
        fields = ('full_name', 'email', 'password')

    def create(self, validated_data):
        return User.objects.create_user(
            username  = validated_data['email'],
            email     = validated_data['email'],
            full_name = validated_data.get('full_name', ''),
            password  = validated_data['password'],
        )

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model  = User
        fields = ('id', 'email', 'full_name')