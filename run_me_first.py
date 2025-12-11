import os, sys


project_name = input("Enter your project name: ")
if input(f"Are you sure you want to name the project '{project_name}'? (y/n): ").lower() != 'y':
    print("Project creation cancelled.")
    exit()
# change the project folder name

path = os.path.abspath(sys.argv[0])
os.rename('project_name', project_name)

with open(f'{project_name}/settings.py', 'r') as file:
    settings_content = file.read()
settings_content = settings_content.replace('project_name', project_name)
with open(f'{project_name}/settings.py', 'w') as file:
    file.write(settings_content)

with open('manage.py', 'r') as file:
    manage_content = file.read()
manage_content = manage_content.replace('project_name', project_name)
with open('manage.py', 'w') as file:
    file.write(manage_content)

with open(f'{project_name}/wsgi.py', 'r') as file:
    wsgi_content = file.read()
wsgi_content = wsgi_content.replace('project_name', project_name)
with open(f'{project_name}/wsgi.py', 'w') as file:
    file.write(wsgi_content)

with open(f'{project_name}/asgi.py', 'r') as file:
    asgi_content = file.read()
asgi_content = asgi_content.replace('project_name', project_name)
with open(f'{project_name}/asgi.py', 'w') as file:
    file.write(asgi_content)

with open(f'{project_name}/urls.py', 'r') as file:
    urls_content = file.read()
urls_content = urls_content.replace('project_name', project_name)
with open(f'{project_name}/urls.py', 'w') as file:
    file.write(urls_content)

print(f"Project '{project_name}' is ready.")

os.remove(path)
print(f"Removed setup script: {path}")