// Jenkinsfile — HackDox CI
//
// Declarative pipeline: builds a throwaway venv, lints, runs the stdlib
// foundation-test runner, then the full pytest suite with JUnit + coverage
// reporting. Written for a Linux/WSL2 Jenkins agent (Java 11+, no Docker
// required) — swap the `sh` steps for `bat` if you ever point a native
// Windows agent at this instead.
//
// Local setup: see JENKINS_SETUP.md.

pipeline {
    agent any

    options {
        timestamps()
        timeout(time: 20, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '20'))
        disableConcurrentBuilds()
    }

    triggers {
        // Local Jenkins isn't reachable from GitHub for a webhook, so we
        // poll instead. Swap for `githubPush()` + a webhook once this runs
        // somewhere internet-reachable.
        pollSCM('H/5 * * * *')
    }

    environment {
        PYTHONPATH = "${WORKSPACE}"
        VENV       = "${WORKSPACE}/.venv"
        REPORTS    = "${WORKSPACE}/reports"
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Set Up Python') {
            steps {
                sh '''
                    python3 -m venv "$VENV"
                    "$VENV/bin/pip" install --upgrade pip
                '''
            }
        }

        stage('Install Dependencies') {
            steps {
                sh '''
                    "$VENV/bin/pip" install -r gameengine/requirements.txt
                    "$VENV/bin/pip" install pytest-cov ruff
                '''
            }
        }

        stage('Lint') {
            steps {
                // Non-blocking: the codebase predates ruff, so a lint
                // finding marks the build UNSTABLE (yellow) rather than
                // failing it. Tighten this to a hard failure once the
                // backlog of findings is cleared.
                catchError(buildResult: 'UNSTABLE', stageResult: 'UNSTABLE') {
                    sh '"$VENV/bin/ruff" check gameengine'
                }
            }
        }

        stage('Foundation Tests') {
            steps {
                // Legacy stdlib-only runner — see run_foundation_tests.py's
                // own docstring for why it exists alongside pytest.
                sh '"$VENV/bin/python" -m gameengine.tests.run_foundation_tests'
            }
        }

        stage('Pytest Suite') {
            steps {
                sh '''
                    mkdir -p "$REPORTS"
                    "$VENV/bin/pytest" gameengine/tests/ \
                        --junitxml="$REPORTS/junit.xml" \
                        --cov=gameengine --cov-report=xml:"$REPORTS/coverage.xml" \
                        -v
                '''
            }
        }
    }

    post {
        always {
            junit testResults: 'reports/junit.xml', allowEmptyResults: true
            archiveArtifacts artifacts: 'reports/*.xml', allowEmptyArchive: true
        }
        success {
            echo "HackDox build #${env.BUILD_NUMBER} green."
        }
        unstable {
            echo "Build unstable — check the Lint stage; tests themselves are green."
        }
        failure {
            echo "Build failed — see console output for the failing stage."
        }
    }
}
