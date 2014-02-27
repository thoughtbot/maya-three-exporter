import sys
import json

from pymel.core import *
from maya.OpenMaya import *
from maya.OpenMayaMPx import *

kPluginTranslatorTypeName = 'Three.js'
kOptionScript = 'ThreeJsExportScript'
kDefaultOptionsString = '0'

FLOAT_PRECISION = 8

class ThreeJsWriter(object):
    def __init__(self):
        self.componentKeys = ['vertices', 'normals', 'colors', 'materials', 'faces', 'bones', 'bakeAnimations']

    def write(self, path, optionString, accessMode):
        self._parseOptions(optionString)

        self.verticeOffset = 0
        self._goToFrame(playbackOptions(minTime=True, query=True))
        self.vertices = []
        self.materials = []
        self.faces = []
        self.normals = []
        self.morphTargets = []
        self.bones = []
        self.animations = []
        self.skinIndices = []
        self.skinWeights = []

        if self.options["bakeAnimations"]:
            print("exporting animations")
            self._exportAnimations()
            self._goToFrame(self.options["startFrame"])
        if self.options["materials"]:
            print("exporting materials")
            self._exportMaterials()
        if self.options["bones"]:
            print("exporting bones")
            self._exportBones()
            print("exporting skins")
            self._exportSkins()
        print("exporting meshes")
        self._exportMeshes()
        print("exporting keyframe animations")
        self._exportKeyframeAnimations()

        print("writing file")
        output = {
            'metadata': {
                'formatVersion': 3.1,
                'generatedBy': 'Maya Exporter'
            },

            'vertices': self.vertices,
            'faces': self.faces,
            'normals': self.normals,
            'materials': self.materials,
        }

        if self.options['bakeAnimations']:
            output['morphTargets'] = self.morphTargets

        if self.options['bones']:
            output['bones'] = self.bones
            output['skinIndices'] = self.skinIndices
            output['skinWeights'] = self.skinWeights

        output['animations'] = self.animations

        with file(path, 'w') as f:
            f.write(json.dumps(output, separators=(",",":")))

    def _parseOptions(self, optionsString):
        self.options = dict([(x, False) for x in self.componentKeys])
        for key in self.componentKeys:
            self.options[key] = key in optionsString
        if self.options["bakeAnimations"]:
            bakeAnimOptionsString = optionsString[optionsString.find("bakeAnimations"):]
            bakeAnimOptions = bakeAnimOptionsString.split(' ')
            self.options["startFrame"] = int(bakeAnimOptions[1])
            self.options["endFrame"] = int(bakeAnimOptions[2])
            self.options["stepFrame"] = int(bakeAnimOptions[3])

    def _exportMeshes(self):
        if self.options['vertices']:
            self._exportVertices()
        for mesh in ls(type='mesh'):
            self._exportMesh(mesh)

    def _exportMesh(self, mesh):
        print("Exporting " + mesh.name())
        print("getting material index")
        materialIndex = self._getMaterialIndex(mesh)
        if self.options['faces']:
            print("Exporting faces")
            self._exportFaces(mesh, materialIndex)
            self.verticeOffset += len(mesh.getPoints())
        if self.options['normals']:
            print("Exporting normals")
            self._exportNormals(mesh)

    def _getMaterialIndex(self, mesh):
        if not hasattr(self, '_materialIndices'):
            self._materialIndices = dict([(mat['DbgName'], i) for i, mat in enumerate(self.materials)])

        if self.options['materials']:
            for engine in mesh.listConnections(type='shadingEngine'):
                for material in engine.listConnections(type='lambert'):
                    if self._materialIndices.has_key(material.name()):
                        return self._materialIndices[material.name()]
        return -1


    def _exportVertices(self):
        self.vertices += self._getVertices()

    def _exportAnimations(self):
        for frame in self._framesToExport():
            self._exportAnimationForFrame(frame)

    def _framesToExport(self):
        return range(self.options["startFrame"], self.options["endFrame"], self.options["stepFrame"])

    def _exportAnimationForFrame(self, frame):
        print("exporting frame " + str(frame))
        self._goToFrame(frame)
        self.morphTargets.append({
            'name': "frame_" + str(frame),
            'vertices': self._getVertices()
        })

    def _getVertices(self):
        return [coord for mesh in ls(type='mesh') for point in mesh.getPoints(space='world') for coord in [round(point.x, FLOAT_PRECISION), round(point.y, FLOAT_PRECISION), round(point.z, FLOAT_PRECISION)]]

    def _goToFrame(self, frame):
        currentTime(frame)

    def _exportFaces(self, mesh, materialIndex):
        typeBitmask = self._getTypeBitmask()
        hasMaterial = materialIndex != -1

        for face in mesh.faces:
            self._exportFaceBitmask(face, typeBitmask, hasMaterial=hasMaterial)
            self.faces += map(lambda x: x + self.verticeOffset, face.getVertices())
            if self.options['materials']:
                if hasMaterial:
                    self.faces.append(materialIndex)
            if self.options['normals']:
                self._exportFaceVertexNormals(face)

    def _exportFaceBitmask(self, face, typeBitmask, hasMaterial=True):
        if face.polygonVertexCount() == 4:
            faceBitmask = 1
        else:
            faceBitmask = 0
        if hasMaterial:
            faceBitmask |= 2
        self.faces.append(typeBitmask | faceBitmask)

    def _exportFaceVertexNormals(self, face):
        for i in range(face.polygonVertexCount()):
            self.faces.append(face.normalIndex(i))

    def _exportNormals(self, mesh):
        for normal in mesh.getNormals():
            self.normals += [round(normal.x, FLOAT_PRECISION), round(normal.y, FLOAT_PRECISION), round(normal.z, FLOAT_PRECISION)]

    def _getTypeBitmask(self):
        bitmask = 0
        if self.options['normals']:
            bitmask |= 32
        return bitmask

    def _exportMaterials(self):
        for mat in ls(type='lambert'):
            self.materials.append(self._exportMaterial(mat))

    def _exportMaterial(self, mat):
        result = {
            "DbgName": mat.name(),
            "blending": "NormalBlending",
            "colorDiffuse": map(lambda i: i * mat.getDiffuseCoeff(), mat.getColor().rgb),
            "colorAmbient": mat.getAmbientColor().rgb,
            "depthTest": True,
            "depthWrite": True,
            "shading": mat.__class__.__name__,
            "transparency": mat.getTransparency().a,
            "transparent": mat.getTransparency().a != 1.0,
            "vertexColors": False
        }
        if isinstance(mat, nodetypes.Phong):
            result["colorSpecular"] = mat.getSpecularColor().rgb
            result["specularCoef"] = mat.getCosPower()

        return result

    def _exportBones(self):
        for joint in ls(type='joint'):
            if joint.getParent():
                parentIndex = self._indexOfJoint(joint.getParent().name())
            else:
                parentIndex = -1
            rotq = joint.getRotation().asQuaternion()
            pos = joint.getTranslation()

            self.bones.append({
                "parent": parentIndex,
                "name": joint.name(),
                "pos": [round(pos.x, FLOAT_PRECISION), round(pos.y, FLOAT_PRECISION), round(pos.z, FLOAT_PRECISION)],
                "rotq": [round(rotq.x, FLOAT_PRECISION), round(rotq.w, FLOAT_PRECISION), round(rotq.z, FLOAT_PRECISION), round(rotq.y, FLOAT_PRECISION)]
            })

    def _indexOfJoint(self, name):
        if not hasattr(self, '_jointNames'):
            self._jointNames = dict([(joint.name(), i) for i, joint in enumerate(ls(type='joint'))])

        if name in self._jointNames:
            return self._jointNames[name]
        else:
            return -1

    def _exportKeyframeAnimations(self):
        hierarchy = []
        i = -1
        frameRate = FramesPerSecond(currentUnit(query=True, time=True)).value()
        for joint in ls(type='joint'):
            hierarchy.append({
                "parent": i,
                "keys": self._getKeyframes(joint, frameRate)
            })
            i += 1

        self.animations.append({
            "name": "skeletalAction.001",
            "length": (playbackOptions(maxTime=True, query=True) - playbackOptions(minTime=True, query=True)) / frameRate,
            "fps": 1,
            "hierarchy": hierarchy
        })


    def _getKeyframes(self, joint, frameRate):
        frames = list(set(keyframe(joint, query=True)))
        frames.sort()
        keys = []
        firstFrame = playbackOptions(minTime=True, query=True)
        lastFrame = playbackOptions(maxTime=True, query=True)

        print("joint " + joint.name() + " has " + str(len(frames)) + " keyframes")
        if len(frames) <= 1:
            frames = sorted(list(set(frames + [firstFrame, lastFrame])))
        for frame in frames:
            self._goToFrame(frame)
            keys.append(self._getCurrentKeyframe(joint, frame, frameRate))
        return keys

    def _getCurrentKeyframe(self, joint, frame, frameRate):
        pos = joint.getTranslation()
        rot = joint.getRotation().asQuaternion()

        return {
            'time': (frame - playbackOptions(minTime=True, query=True)) / frameRate,
            'pos': map(lambda x: round(x, FLOAT_PRECISION), [pos.x, pos.y, pos.z]),
            'rot': map(lambda x: round(x, FLOAT_PRECISION), [rot.x, rot.w, rot.z, rot.y]),
            'scl': [1,1,1]
        }

    def _exportSkins(self):
        for mesh in ls(type='mesh'):
            print("exporting skins for mesh: " + mesh.name())
            skins = filter(lambda skin: mesh in skin.getOutputGeometry(), ls(type='skinCluster'))
            if len(skins) > 0:
                print("mesh has " + str(len(skins)) + " skins")
                skin = skins[0]
                joints = skin.influenceObjects()
                for weights in skin.getWeights(mesh.vtx):
                    numWeights = 0

                    for i in range(0, len(weights)):
                        if weights[i] > 0:
                            self.skinWeights.append(weights[i])
                            self.skinIndices.append(self._indexOfJoint(joints[i]))
                            numWeights += 1

                    for i in range(0, 2 - numWeights):
                        self.skinWeights.append(0)
                        self.skinIndices.append(0)
            else:
                print("mesh has no skins, appending 0")
                for i in range(0, len(mesh.getPoints()) * 2):
                    self.skinWeights.append(0)
                    self.skinIndices.append(0)

class NullAnimCurve(object):
    def getValue(self, index):
        return 0.0

class ThreeJsTranslator(MPxFileTranslator):
    def __init__(self):
        MPxFileTranslator.__init__(self)

    def haveWriteMethod(self):
        return True

    def filter(self):
        return '*.js'

    def defaultExtension(self):
        return 'js'

    def writer(self, fileObject, optionString, accessMode):
        path = fileObject.fullName()
        writer = ThreeJsWriter()
        writer.write(path, optionString, accessMode)


def translatorCreator():
    return asMPxPtr(ThreeJsTranslator())

def initializePlugin(mobject):
    mplugin = MFnPlugin(mobject)
    try:
        mplugin.registerFileTranslator(kPluginTranslatorTypeName, None, translatorCreator, kOptionScript, kDefaultOptionsString)
    except:
        sys.stderr.write('Failed to register translator: %s' % kPluginTranslatorTypeName)
        raise

def uninitializePlugin(mobject):
    mplugin = MFnPlugin(mobject)
    try:
        mplugin.deregisterFileTranslator(kPluginTranslatorTypeName)
    except:
        sys.stderr.write('Failed to deregister translator: %s' % kPluginTranslatorTypeName)
        raise

class FramesPerSecond(object):
    MAYA_VALUES = {
        'game': 15,
        'film': 24,
        'pal': 25,
        'ntsc': 30,
        'show': 48,
        'palf': 50,
        'ntscf': 60
    }

    def __init__(self, fpsString):
        self.fpsString = fpsString

    def value(self):
        if self.fpsString in FramesPerSecond.MAYA_VALUES:
            return FramesPerSecond.MAYA_VALUES[self.fpsString]
        else:
            return int(filter(lambda c: c.isdigit(), self.fpsString))
