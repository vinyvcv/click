import bcrypt

senha_plana = "Click@Visto"
hash_senha = bcrypt.hashpw(senha_plana.encode('utf-8'), bcrypt.gensalt())

print("HASH GERADO:")
print(hash_senha.decode())
