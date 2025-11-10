from flask import Flask, jsonify
from .models import db, init_db
from .follow_status import bp as follow_bp

def create_app(test_config=None):
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = test_config.get('SQLALCHEMY_DATABASE_URI', 'sqlite:///:memory:') if test_config else 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    app.register_blueprint(follow_bp)

    @app.route('/health')
    def health():
        return jsonify({'ok': True})

    with app.app_context():
        init_db()

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
