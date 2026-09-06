"""Explicitly populate the prototype database with demonstration records."""

from app import seed_demo, seed_env, seed_expert, seed_rich


def main():
    seed_demo()
    seed_expert()
    seed_env()
    seed_rich()
    print("Demo data initialized.")


if __name__ == "__main__":
    main()
